from ws import connect
import sys, tty
from pythreader import PyThread, synchronized

my_name = sys.argv[1]
url = sys.argv[2] if len(sys.argv) > 2 else "ws://localhost:8080/chat"

class ChatClient(PyThread):
    
    class TermWReader(PyThread):
        
        def __init__(self, master):
            PyThread.__init__(self)
            self.Master = master
            self.Stop = False
        
        def run(self):
            while not self.Stop:
                line = input("> ").strip()
                if line:
                    if line[0] == '@':
                        to, msg = line.split(None, 1)
                        to = to[1:]
                    elif line[0] == '.':
                        to = '.'
                        msg = line[1:].strip()
                    else:
                        to = ''
                        msg = line
                    self.Master.send(to, msg)
            self.Master = None
    
        def stop(self):
            self.Stop = True
            
    def __init__(self, ws):
        PyThread.__init__(self)
        self.WS = ws
        
    def run(self):
        reader = self.TermWReader(self)
        reader.start()
        self.WS.run(self)
        reader.stop()
        reader.join()
        
    @synchronized
    def send(self, to, message):
        if message:
            self.WS.send("%s:%s" % (to, message))
            
    @synchronized
    def on_message(self, ws, message):
        src, dst, message = message.split(":", 2)
        if src == "[chat]":
            print("! %s" % (message,))
        elif dst:
            print ("@%s->@%s: %s" % (src, dst, message))
        else:
            print ("@%s: %s" % (src, message))
        
    @synchronized
    def on_close(self, ws, status):
        print("[Closed: %s]" % (status,))
    
ws = connect(url+"/my_name", headers={"X-Chat-Name": my_name})
print("Connected to server. Press space to enter a message.")
c = ChatClient(ws)
c.run()
