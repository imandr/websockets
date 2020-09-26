from ws import connect
import time

url = "ws://localhost:8765/echo"

print(f"connecting to {url} ...")
client = connect(url)
name = input("What's your name? ")

for t in range(5):
    ping = f"{name} {t}"
    client.send(ping)
    print(f"> {ping}")
    pong = client.recv()
    print(f"< {pong}")
    time.sleep(1.0)
client.close()

