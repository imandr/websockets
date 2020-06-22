from socket import *
from pythreader import TaskQueue, Task, Primitive, PyThread, synchronized
from threading import RLock
import sys, hashlib, base64, struct, random, traceback, os
import numpy as np
from urllib.parse import urlsplit, urlunsplit

class EOF(Exception):
    def __init__(self, message):
        self.Message = message
        
    def __str__(self):
        return f"Websocket EOF: {self.Message}"
    
    __repr__ = __str__

WebSocketVersion = "13"

class WebsocketPeer(Primitive):
    
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    Debug = False
        
    def __init__(self, sock = None, send_masked = False, max_fragment = None):
        Primitive.__init__(self)
        self.Sock = sock
        self.Closed = False
        self.CloseReceived = False
        self.CloseSent = False
        self.SendMasked = send_masked
        self.ClosedCode = None
        self.ClosedStatus = ""
        self.MaxFragment = max_fragment
        self.SendLock = RLock()
        self.RecvLock = RLock()
        
    @synchronized
    def set_socket(self, sock):
        if self.Sock is None:
            self.Sock = sock
    
    def peer_address(self):
        return self.Sock.getpeername()
        
    def read_line(self):
        l = b""
        done = False
        while not done:
            #print("sock:", self.Sock)
            c = self.Sock.recv(1, MSG_WAITALL)
            #print("sock:", self.Sock)
            #print("c:", c)
            if not c:
                raise EOF("Peer disconnected while reading the handshake")
            l += c
            done = c == b'\n'
            #print("done:", done)
        return l.decode("utf-8")
        
    def recv_handshake(self):
        with self.RecvLock:
            headline = None
            headers = {}
            done = False
            while not done:
                l = self.read_line()
                l = l.strip()
                #print("line:[%s]" % (l,))
                if not l:
                    done = True
                else:
                    if headline is None:
                        headline = l
                    else:
                        words = l.split(":", 1)
                        headers[words[0]] = words[1].strip()
            return headline, headers

    def send_handshake(self, headline, headers):
        with self.SendLock:
            response = [headline] + ["%s: %s" % (k, v) for k, v in headers.items()]
            response = "\r\n".join(response) + "\r\n\r\n"
            self.Sock.sendall(response.encode("utf-8"))
        
    def recv_fragment(self):
        with self.RecvLock:
            if self.Closed:
                raise EOF("Websocket has been closed")
        
            b = self.Sock.recv(1, MSG_WAITALL)
            if not b:
                raise EOF("Peer disconnected while reading a fragment")
            b = b[0]
            fin = (b >> 7) & 1
            opcode = b & 15;

            b = self.Sock.recv(1, MSG_WAITALL)
            if not b:
                raise EOF("Peer disconnected while reading a fragment")
            b = b[0]
            mask_flag = (b >> 7) & 1
            length = b & 127
        
            if self.Debug:
                print("recv_fragment: fin:", fin, "   opcode:", opcode, "   mask_flag:", mask_flag, "   length:", length)
        
            assert length < 126
        
            mask = None
        
            if mask_flag:
                mask = self.Sock.recv(4, MSG_WAITALL)
                if len(mask) != 4:
                    raise EOF("Peer disconnected while reading a fragment")
            
                if self.Debug:
                    print("        mask:", mask.hex())
            
            fragment = self.Sock.recv(length, MSG_WAITALL)
            if len(fragment) != length:
                raise EOF(f"Peer disconnected while reading fragment body. Expected {length}, got {len(fragment)}")
            
            if mask:
                fragment = self.mask(mask, fragment)

            if self.Debug:
                if fragment:
                    print("        fragment: [%s]" % (fragment.hex(),))
            
            data = fragment
            if opcode == 8: # close
                self.CloseReceived = True
                if length >= 2:
                    self.ClosedCode = struct.unpack("!H", fragment[:2])[0]
                    if length > 2:
                        self.ClosedReason = fragment[2:].decode("utf-8")     
                data = b''
        
            if opcode == 9: # ping
                self.Sock.send(b"\x0a\x00")
                
            if self.Debug:
                if opcode == 1:
                    print('        text: "%s"' % (data.decode("utf-8"),))
                elif opcode == 2:
                    print("        data: [%s]" % (data.hex(),))

            return fin, opcode, data
        
    #@synchronized
    def send_close(self, code=None, reason=None):
        with self.SendLock:
            body = b''
            if code is not None:
                body = struct.pack('!H', code)
                if reason:
                    body = body + reason.encode("utf-8")
            self.send_fragment(True, 8, self.SendMasked, body)
        
    #@synchronized
    def recv(self):
        #print("recv(): Closed=", self.Closed)
        if self.Closed:
            raise EOF("Websocket has been closed")
        fragments = []
        final = False
        eof = False
        binary = None
        first_fragment = True
        while not final and not eof:
            try:    final, opcode, fragment = self.recv_fragment()
            except EOF as e:
                self.shutdown(str(e))
                raise
            if first_fragment:
                assert opcode != 0
                binary = opcode == 2
                first_fragment = False
            if fragment:
                fragments.append(fragment)
            eof = opcode == 8
        data = b''.join(fragments)
        if not binary:  data = data.decode("utf-8")
        if eof: 
            #print("recv: closing")
            self.close()
        return data
        
    def send_pong(self):
        with self.SendLock:
            self.Sock.send(b"\x0a\x00")
            
    def mask(self, mask, buf):
        # mask: bytes(4)
        n = (len(buf)+3)//4
        l = len(buf)
        mask = (mask*n)[:len(buf)]
        return bytes([x^m for x, m in zip(buf, mask)])
        
    def send_fragment(self, fin, opcode, mask, data):
        with self.SendLock:
            assert opcode < 16
            fin = 2**7 if fin else 0
            hdr = bytes([opcode | fin])
            n = len(data)
            mask = 2**7 if mask else 0
            if n < 127:
                hdr = hdr + struct.pack('!B', n+mask)
            elif n < 2**16:
                hdr = hdr + struct.pack('!B', 126+mask) + struct.pack('!H', n)
            else:
                hdr = hdr + struct.pack('!B', 127+mask) + struct.pack('!Q', n)
            if mask:
                r1 = random.randint(0, 0xFFFF)
                r2 = random.randint(0, 0xFFFF)
                mask = struct.pack('!H', r1) + struct.pack('!H', r2)
                hdr = hdr + mask
                data = self.mask(mask, data)
            self.Sock.sendall(hdr)
            if data:
                self.Sock.sendall(data)
            
    @synchronized
    def shutdown(self, status=""):
        if self.Sock is not None:
            self.Sock.close()
            self.Sock = None
            self.CloseStatus = status
        self.Closed = True
        
    
    #
    # Usable methods
    #
    
    def send(self, message):
        with self.SendLock:
            if not self.CloseReceived and not self.Closed and not self.CloseSent:
                binary = isinstance(message, bytes)
                if not binary:
                    message = message.encode("utf-8")
                
                first_fragment = True
                while message:
                    n = len(message) 
                    if self.MaxFragment is not None:
                        n = min(n, self.MaxFragment)
                    fragment = message[:n]
                    message = message[n:]
                    opcode = 0 if not first_fragment else (2 if binary else 1)
                    self.send_fragment(len(message) == 0,    # fin
                        opcode, self.SendMasked, fragment)
                first_fragment = False
    
    @synchronized
    def close(self, code=1000, reason=None):
        #print("call close()")
        if not self.Closed:
            if not self.CloseSent:
                self.send_close(code, reason)
                self.CloseSent = True
            while not self.CloseReceived:
                self.recv_fragment()
            self.shutdown()
            
    def messages(self):
        while not self.Closed:
            try:    msg = self.recv()
            except EOF as e:
                self.ClosedStatus = e.Message
                break
            if msg:
                yield msg
        
    def run(self, callback_delegate=None):
        stop = False
        for message in self.messages():
            if callback_delegate is not None:
                stop = callback_delegate.on_message(self, message) == "stop"
                if stop:
                    break
        else:
            if callback_delegate is not None:
                callback_delegate.on_close(self, self.ClosedStatus)                    

class WebsocketReceiver(Task):

    def __init__(self, app, sock, address, handler_factory, ws_args):
        Task.__init__(self)
        self.Sock = sock
        self.HandlerFactory = handler_factory
        self.Address = address
        self.WSArgs = ws_args
        self.App = app
        
    def run(self):
        try:
            #
            # Handshake
            #
            ws = WebsocketPeer(self.Sock, **self.WSArgs)
            request_headline, request_headers = ws.recv_handshake()
            path = request_headline.split()[1]
            
            #print("WebsocketReceiver: handshake received:", request_headline, request_headers)
            
            handler = self.HandlerFactory(self.App, ws)
            assert isinstance(handler, WSHandler)
            
            headers = handler.handshake(self.Address, path, request_headers) or {}
            
            #print("WebsocketReceiver: initialized:", headers)
            
            h = hashlib.sha1()
            key = request_headers["Sec-WebSocket-Key"] + WebsocketPeer.GUID
            h.update(key.encode("utf-8"))
            response_headers = {
                    "Upgrade": "websocket",
                    "Connection": "Upgrade",
                    "Sec-WebSocket-Accept": base64.b64encode(h.digest()).decode("utf-8")
            }
            
            response_headers.update(headers)
            ws.send_handshake("HTTP/1.1 101 Switching Protocols", response_headers)
            
            #print("WebsocketReceiver: handler created:", handler)
            handler.run()
        except:
            traceback.print_exc()
            raise
        finally:
            ws.close()

class WebsocketServer(PyThread):
    
    def __init__(self, port, handler_factory, app, max_connections=10, max_queued=30, **ws_args):
        PyThread.__init__(self)
        self.Port = port
        self.HandlerFactory = handler_factory
        self.HandlerQueue = TaskQueue(max_connections, capacity=max_queued)
        self.App = app
        self.WSArgs = ws_args
        
    def run(self):
        srv_sock = socket(AF_INET, SOCK_STREAM)
        srv_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        srv_sock.bind(("", self.Port))
        srv_sock.listen(5)
        
        while True:
            sock, address = srv_sock.accept()
            receiver = WebsocketReceiver(self.App, sock, address, self.HandlerFactory, self.WSArgs)
            try:
                self.HandlerQueue.addTask(receiver)
            except:
                # ws response here !
                sock.close()

class WSHandler(object):
    
    def __init__(self, app, ws):
        #Primitive.__init__(self)
        self.App = app
        self.WS = ws
        
    def handshake(self, client_address, path, request_headers):
        self.ClientAddress = client_address
        self.Path = path
        self.RequestHeaders = request_headers
        return {}
        
    def run(self):
        self.WS.close()
        
    def send(self, message):
        return self.WS.send(message)
        
    def recv(self):
        return self.WS.recv()
        
    def __iter__(self):
        return self.WS.messages()
        
class WSApp(Primitive):
    
    def __init__(self, handler_factory):
        Primitive.__init__(self)
        self.HandlerFactory = handler_factory
        
    def run_server(self, port, **args):
        server = WebsocketServer(port, self.HandlerFactory, self, **args)
        server.start()
        server.join()
        
def connect(url, headers = {}, **args):
        parsed = urlsplit(url, scheme="ws")
        assert parsed.scheme == "ws"
        host = parsed.hostname
        port = parsed.port
        uri = urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))
        if not uri or uri[0] != '/':
            uri = "/" + uri
        
        headline = f"GET {uri} HTTP/1.1"

        key = os.urandom(16)
        key = base64.b64encode(key).decode("utf-8")
        hdict = {
            "Host":                 f"{host}:{port}",
            "Upgrade":              "websocket",
            "Connection":           "Upgrade",
            "Sec-WebSocket-Version": WebSocketVersion
        }
        
        if headers:
            hdict.update(headers)
            
        hdict["Sec-WebSocket-Key"] = key
        
        sock = socket(AF_INET, SOCK_STREAM)
        sock.connect((host, port))
        ws = WebsocketPeer(sock, send_masked = True, **args)
        ws.send_handshake(headline, hdict)
        
        response_headline, response_headers = ws.recv_handshake()
        #print("response_headline:", response_headline)
        protocol, status, message = response_headline.split(None, 2)
        status = int(status)

        if status == 101:
            ws.Protocol = protocol
            ws.ConnectMessage = message
            ws.ResponseHeaders = response_headers
            return ws
        else:
            raise ConnectionError(status, message)
        
    