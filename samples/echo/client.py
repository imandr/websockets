from ws import connect

url = "ws://localhost:8765/echo"

client = connect(url)
name = input("What's your name? ")
client.send(name)
print(f"> {name}")
greeting = client.recv()
print(f"< {greeting}")
client.close()

