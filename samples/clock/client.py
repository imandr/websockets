from ws import connect

url = "ws://localhost:8765/clock"

client = connect(url)

n = 2

for msg in client.messages():
    if n <= 0:
        client.close()
        break
    print (msg)
    n -= 1