from ws import WSHandler, WSApp
from pythreader import synchronized

class ChatHandler(WSHandler):
    
    def handshake(self, address, path, headers):
        self.Name = headers["X-Chat-Name"]
        self.App.register(self, self.Name)
        
    def run(self):
        for msg in self:
            if isinstance(msg, bytes):
                msg = msg.decode("utf-8")
            dst, text = msg.split(":", 1)
            self.App.send(self.Name, dst, text)
        self.App.unregister(self.Name)
        
    def say(self, src, dst, message):
        message = "%s:%s:%s" % (src, dst, message)
        self.send(message)
        
class ChatApp(WSApp):
    
    def __init__(self, handler_factory):
        WSApp.__init__(self, handler_factory)
        self.Clients = {}       # name -> handler
        
    @synchronized
    def register(self, handler, name):
        print("register:", name)
        if name in self.Clients:
            raise ValueError("Already registered")
        self.Clients[name] = handler
        self.send("[chat]", None, "%s connected" % (name,), exclude=name)
        
    @synchronized
    def unregister(self, name):
        print("unregister:", name)
        if name in self.Clients:
            del self.Clients[name]
        self.send("[chat]", None, "%s disconnected" % (name,))
        
    @synchronized
    def send(self, src, dst, text, exclude=None):
        print("send: %s->%s: %s", src, dst or "", text)
        to = [dst] if dst else list(self.Clients.keys())
        for name in to:
            if name in self.Clients and name != src and name != exclude:
                self.Clients[name].say(src, dst, text)
    

app = ChatApp(ChatHandler)
app.run_server(8765)
