"""Send a Python file to the Blender MCP addon socket (localhost:9876) and print the result."""
import json, socket, sys

def run(code, timeout=600):
    s = socket.create_connection(("localhost", 9876), timeout=timeout)
    s.sendall(json.dumps({"type": "execute_code", "params": {"code": code}}).encode())
    buf = b""
    while True:
        chunk = s.recv(1 << 16)
        if not chunk:
            break
        buf += chunk
        try:
            return json.loads(buf.decode())
        except json.JSONDecodeError:
            continue
    return json.loads(buf.decode())

if __name__ == "__main__":
    src = open(sys.argv[1], encoding="utf-8").read()
    r = run(src)
    res = r.get("result", r)
    if isinstance(res, dict) and "result" in res:
        print(res["result"])
    else:
        print(json.dumps(r, indent=1, ensure_ascii=False)[:4000])
