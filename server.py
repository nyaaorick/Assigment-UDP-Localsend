import socket
import os
import base64

def handle_file_transfer(filename, data_port):
    # Create a new socket for data transfer
    data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data_sock.bind(('localhost', data_port))
    print(f"Data transfer socket listening on port {data_port}")

    file_path = os.path.join("serverfile", filename)
    file_size = os.path.getsize(file_path)
    chunk_size = 1024  # 1KB chunks

    while True:
        try:
            # Receive file request
            data, addr = data_sock.recvfrom(1024)
            request = data.decode('utf-8')
            print(f"Received request: {request}")

            if request.startswith("FILE CLOSE"):
                # Handle close request
                response = f"FILE {filename} CLOSE_OK"
                data_sock.sendto(response.encode('utf-8'), addr)
                break

            # Parse the request
            parts = request.split()
            if len(parts) >= 7 and parts[0] == "FILE" and parts[2] == "GET":
                start = int(parts[4])
                end = int(parts[6])

                # Read the requested chunk
                with open(file_path, 'rb') as f:
                    f.seek(start)
                    chunk = f.read(end - start)
                    encoded_chunk = base64.b64encode(chunk).decode('utf-8')

                # Send the chunk
                response = f"FILE {filename} OK START {start} END {end} DATA {encoded_chunk}"
                data_sock.sendto(response.encode('utf-8'), addr)

        except Exception as e:
            print(f"Error in file transfer: {str(e)}")
            break

    data_sock.close()

def start_server():
    # 直接使用 localhost 和固定端口
    host = 'localhost'
    port = 51234
    data_port = 51235  # data transfer port

    # Create a UDP socket
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Bind the socket to the address and port
    server_sock.bind((host, port))

    print(f"Server listening on {host}:{port}")

    while True:
        # Receive data from client
        data, addr = server_sock.recvfrom(1024)
        message = data.decode()
        print(f"Received message from {addr}: {message}")

        # Parse the message
        parts = message.split()
        if len(parts) >= 2 and parts[0] == "DOWNLOAD":
            filename = parts[1]
            file_path = os.path.join("serverfile", filename)
            
            if os.path.exists(file_path):
                # File exists, send OK response with file info
                file_size = os.path.getsize(file_path)
                response = f"OK {filename} SIZE {file_size} PORT {data_port}"
                server_sock.sendto(response.encode('utf-8'), addr)
                print(f"Sent response: {response}")
                
                # Start file transfer handling
                handle_file_transfer(filename, data_port)
            else:
                # File doesn't exist, send error response
                response = f"ERR {filename} NOT_FOUND"
                server_sock.sendto(response.encode('utf-8'), addr)
                print(f"Sent response: {response}")

if __name__ == "__main__":
    start_server()

        
