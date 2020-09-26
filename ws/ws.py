from socket import *
from pythreader import Primitive, synchronized
from threading import RLock
import sys, hashlib, base64, struct, random, traceback, os, errno, time
from urllib.parse import urlsplit, urlunsplit
from socket import timeout as socket_timeout

class EOF(Exception):
    def __init__(self, message=""):
        self.Message = message
        
    def __str__(self):
        msg = ": "+self.Message if self.Message else ""
        return f"Websocket EOF{msg}"
    
    __repr__ = __str__

class Timeout(Exception):
    def __init__(self, message=""):
        self.Message = message
        
    def __str__(self):
        msg = ": "+self.Message if self.Message else ""
        return f"Websocket timeout{msg}"
    
    __repr__ = __str__


class WebsocketHeader(object):
    
    def __init__(self, headline, headers):
        self.Path = self.Status = self.Method = None
        self.Headline = headline
        self.Headers = headers
        words = headline.split(None, 2)
        if words[0].lower().startswith("http/"):
            # response
            self.Protocol, status, self.Message = words
            self.Status = int(status)
        else:
            # request
            self.Method, self.Path, self.Protocol = words
        
WebsocketRespone = WebsocketRequest = WebsocketHeader

WebSocketVersion = "13"

class WebsocketPeer(Primitive):
    
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"           # defined by RFC6455
    
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
        self.BufferedFragments = []         # [(fin, opcode, data),... ]
        
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
        # receive handshake response
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
            return WebsocketHeader(headline, headers)
            
    recv_request = recv_handshake
    recv_response = recv_handshake

    def send_response(self, request, headers={}, status="101 Switching Protocols"):
        headline = f"HTTP/1.1 {status}"
        h = hashlib.sha1()
        key = request.Headers["Sec-WebSocket-Key"] + WebsocketPeer.GUID
        h.update(key.encode("utf-8"))
        response_headers = {
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "Sec-WebSocket-Accept": base64.b64encode(h.digest()).decode("utf-8")
        }
        response_headers.update(headers)
        
        with self.SendLock:
            response = [headline] + ["%s: %s" % (k, v) for k, v in response_headers.items()]
            response = "\r\n".join(response) + "\r\n\r\n"
            self.Sock.sendall(response.encode("utf-8"))
            
    def send_request(self, uri, host, port, headers={}):
        headline = f"GET {uri} HTTP/1.1"
        key = os.urandom(16)
        key = base64.b64encode(key).decode("utf-8")
        hdict = {
            "Host":                 f"{host}:{port}",
            "Upgrade":              "websocket",
            "Connection":           "Upgrade",
            "Sec-WebSocket-Version": WebSocketVersion,
            "Sec-WebSocket-Key":    key
        }
        
        hdict.update(headers)

        with self.SendLock:
            request = [headline] + ["%s: %s" % (k, v) for k, v in hdict.items()]
            request = "\r\n".join(request) + "\r\n\r\n"
            self.Sock.sendall(request.encode("utf-8"))
            
    def recv_fragment(self, buffered=None):
        fin, opcode, data = None, None, None
        close_received = False
        with self.RecvLock:
            if self.CloseReceived:
                raise EOF("Websocket has been closed")
        
            if buffered is not None:
                b = buffered
            else:
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
        
            if length < 126:
                pass
            elif length == 126:
                l = self.Sock.recv(2, MSG_WAITALL)
                length = struct.unpack("!H", l)[0]
            else:
                l = self.Sock.recv(8, MSG_WAITALL)
                length = struct.unpack("!Q", l)[0]

            if self.Debug:
                print("recv_fragment: fin:", fin, "   opcode:", opcode, "   mask_flag:", mask_flag, "   length:", length)
        

        
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
                close_received = True
        
            if opcode == 9: # ping
                self.Sock.send(b"\x0a\x00")
                
            if self.Debug:
                if opcode == 1:
                    print('        text: "%s"' % (data.decode("utf-8"),))
                elif opcode == 2:
                    print("        data: [%s]" % (data.hex(),))

        if close_received:      # do this after releasing the RecvLock
            self.send_close()

        return fin, opcode, data
        
    #@synchronized
    def send_close(self, code=None, reason=None):
        with self.SendLock:
            if not self.CloseSent:
                body = b''
                if code is not None:
                    body = struct.pack('!H', code)
                    if reason:
                        body = body + reason.encode("utf-8")
                self.send_fragment(True, 8, self.SendMasked, body)
                #print("close sent")
                self.CloseSent = True
        
    def peek(self, timeout=0):
        if self.closed():
            raise EOF("Websocket has been closed")
        with self.RecvLock:
            saved_timeout = self.Sock.gettimeout()
            self.Sock.settimeout(timeout)
            try:
                try:    b = self.Sock.recv(1)
                except socket_timeout:
                    return False
                except OSError as exc:
                    if exc.errno == errno.EWOULDBLOCK:
                        return False
                    else:
                        raise
                try:
                    fragment = self.recv_fragment(buffered=b)
                    self.BufferedFragments.append(fragment)
                except EOF:
                    pass
                return True
            finally:
                self.Sock.settimeout(saved_timeout)
                 
    def recv(self, timeout=None):
        #print("recv(): Closed=", self.Closed)
        with self.RecvLock:
            if self.closed():
                raise EOF("Websocket has been closed")
            fragments = []
            final = False
            eof = False
            binary = None
            first_fragment = True
            while not final and not eof:
                if timeout is not None:
                    if not self.peek(timeout):
                        raise Timeout()
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
            
    def skip_one(self, tmo=None):
        try:    self.recv(timeout=tmo)
        except Timeout:
            pass
        except EOF:
            pass

    def skip(self, tmo=None):
        t0 = time.time()
        t1 = None if tmo is None else t0 + tmo
        while True:
            dt = None if tmo is None else t1 - time.time()
            if dt is None or dt > 0.0:
                self.skip_one(dt)
            elif dt <= 0.0:
                break

    def send_pong(self):
        with self.SendLock:
            self.Sock.send(b"\x0a\x00")
            
    def mask(self, mask, buf):
        # mask: bytes(4)
        n = (len(buf)+3)//4
        l = len(buf)
        mask = (mask*n)[:len(buf)]
        return bytes([x^m for x, m in zip(buf, mask)])
        
    @synchronized
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
            self.Sock.sendall(hdr + (data or b''))
            
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
    
    @synchronized
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
            self.send_close(code, reason)
            while not self.CloseReceived:
                self.recv_fragment()
            #print("close received")
            self.shutdown()
            #print("closed")
        else:
            #print("already closed")
            pass
            
    def closed(self):
        return self.CloseReceived or self.Closed
            
    def messages(self):
        while not self.closed():
            try:    msg = self.recv()
            except EOF as e:
                self.ClosedStatus = e.Message
                break
            if msg:
                yield msg
                
    def __iter__(self):
        return self.messages()
        
    def run(self, callback_delegate=None):
        stop = False
        for message in self.messages():
            if callback_delegate is not None and hasattr(callback_delegate, "on_message"):
                stop = callback_delegate.on_message(self, message) == "stop"
                if stop:
                    break
        else:
            if callback_delegate is not None and hasattr(callback_delegate, "on_close"):
                callback_delegate.on_close(self, self.ClosedStatus)      


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
        ws.send_request(uri, host, port)
        
        response = ws.recv_response()

        if response.Status == 101:
            ws.Protocol = response.Protocol
            ws.ConnectMessage = response.Message
            ws.ResponseHeaders = response.Headers
            return ws
        else:
            raise ConnectionError(response.Status, response.Message)
        
    