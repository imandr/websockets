from ws import WSHandler, WSApp
import time

class ClockHandler(WSHandler):
    
    def handshake(self, address, request):
        print(f"Server initialized at {request.Path} with headers:")
        for k, v in request.Headers.items():
            print(f"   {k}: {v}")
        
    def run(self):
        while not self.WS.closed():
            self.WS.send(time.ctime())
            self.WS.skip(1.0)

app = WSApp(ClockHandler)
app.run_server(8765)
    
    