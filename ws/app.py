import fnmatch
from pythreader import Primitive
from .server import WebsocketServer

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
        
class WSApp(Primitive):
    
    def __init__(self, handler_map = None):
        #
        # handler_map:
        #   - WSHandler subclass - all in one handler
        #   - [(pattern, class), ...]
        #.  - {pattern:class, ...}
        #
        Primitive.__init__(self)
        self.Map = []
        if isinstance(handler_map, list):
            self.Map = handler_map
        elif isinstance(handler_map, dict):
            self.Map = list(handler_map.items())
        else:
            self.Map = [('*',handler_map)]
            
    def createHandler(self, ws, request):
        path = request.Path
        for pattern, clas in self.Map:
            if fnmatch.fnmatch(path, pattern):
                return clas(self, ws)
        else:
            return None
        
    def run_server(self, port, **args):
        server = WebsocketServer(port, self, **args)
        server.start()
        server.join()


