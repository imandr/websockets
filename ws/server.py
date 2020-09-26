from socket import *
from pythreader import TaskQueue, Task, PyThread
from .ws import WebsocketPeer, WebsocketRequest
import traceback
                
class WebsocketClientConnection(Task):

    def __init__(self, app, sock, address, ws_args):
        Task.__init__(self)
        self.Sock = sock
        self.Address = address
        self.WSArgs = ws_args
        self.App = app
        
    def run(self):
        try:
            #
            # Handshake
            #
            ws = WebsocketPeer(self.Sock, **self.WSArgs)
            request = ws.recv_request()
            
            handler = self.App.createHandler(ws, request)
            if handler is None:
                ws.send_response(request, status="404 Not found")
            else:
                headers = handler.handshake(self.Address, request) or {}
                ws.send_response(request, headers=headers)
                handler.run()
        except:
            traceback.print_exc()
            raise
        finally:
            ws.close()

class WebsocketServer(PyThread):
    
    def __init__(self, port, app, max_connections=10, max_queued=30, **ws_args):
        PyThread.__init__(self)
        self.Port = port
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
            receiver = WebsocketClientConnection(self.App, sock, address, self.WSArgs)
            try:
                self.HandlerQueue.addTask(receiver)
            except:
                # ws response here !
                sock.close()
