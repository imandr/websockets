from ws import WSHandler, WSApp

class EchoHandler(WSHandler):
    
    def handshake(self, address, path, headers):
        print(f"Server initialized at {path} with headers:")
        for k, v in headers.items():
            print(f"   {k}: {v}")
        
    def run(self):
        for msg in self:
            self.send(msg)

app = WSApp(EchoHandler)
app.run_server(8765)
    
    