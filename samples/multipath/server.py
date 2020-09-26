import time
from ws import WSHandler, WSApp

class Common(WSHandler):

    def handshake(self, address, request):
        print(f"Server initialized at {request.Path} with headers:")
        for k, v in request.Headers.items():
            print(f"   {k}: {v}")
        
class EchoHandler(Common):
    
    def run(self):
        for msg in self.WS:
            self.WS.send(msg)

class ClockHandler(Common):
    
    def run(self):
        while not self.WS.closed():
            self.WS.send(time.ctime())
            self.WS.skip(1.0)

app = WSApp({
    "/clock":   ClockHandler,
    "/echo":    EchoHandler
})
app.run_server(8765)
    
    