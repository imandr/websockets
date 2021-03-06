from ws import WSHandler, WSApp

class EchoHandler(WSHandler):
    
    def handshake(self, address, request):
        print(f"Server initialized at {request.Path} with headers:")
        for k, v in request.Headers.items():
            print(f"   {k}: {v}")
        
    def run(self):
        for msg in self.WS:
            self.WS.send(msg)

app = WSApp(EchoHandler)
app.run_server(8080)
    
    
