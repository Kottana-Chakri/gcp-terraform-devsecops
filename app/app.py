
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import socket
from datetime import datetime, timezone

class DevOpsHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/health":
            data = {
                "status": "healthy",
                "application": "DevOps Welcome App",
                "hostname": socket.gethostname(),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            body = json.dumps(data, indent=2).encode()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/":
            html = """
            <html>
              <head><title>DevOps Welcome App</title></head>
              <body style="font-family:Arial;text-align:center;padding:60px">
                <h1>Welcome to My DevOps Project!</h1>
                <h2>Running on Google Cloud</h2>
                <p>Infrastructure: Terraform</p>
                <p>Security: SonarQube and Trivy</p>
                <p>Application: Python</p>
                <a href="/health">Check application health</a>
              </body>
            </html>
            """

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

        else:
            self.send_error(404, "Page not found")


server = HTTPServer(("0.0.0.0", 8080), DevOpsHandler)
print("DevOps application running on port 8080")
server.serve_forever()
