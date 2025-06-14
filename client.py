import socket
import os
import base64
import time

def sendAndReceive(socket, message, server_address, initial_timeout=1.0, max_retries=5):
    timeout = initial_timeout
    retries = 0

    while retries < max_retries:
        try:
            socket.settimeout(timeout)

            socket.sendto(message.encode('utf-8'), server_address)
            print(f"Sent: {message}")



            response, addr= socket.recvfrom(65535)
            print(f"Received: {response.decode('utf-8')}")
            return response.decode('utf-8'), addr
        
        except socket.timeout:
            retries += 1
            if retries < max_retries:
                timeout *= 2
                if timeout > 10:
                    raise socket.timeout("Max retries reached")
                time.sleep(timeout)
            else:
                raise socket.timeout("Max retries reached")

    

            

    raise socket.timeout("Max retries reached")

def download_file(filename, server_host, data_port, file_size):
    # Create a new socket for data transfer
    data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_address = (server_host, data_port)
    
    #read file from serverfile
    file_path = os.path.join("clientfile", filename)
    
    chunk_size = 1024  # 1KB chunks
    bytes_received = 0
    
    try:
        with open(file_path, 'wb') as f:
            while bytes_received < file_size:
                # Calculate chunk boundaries
                start = bytes_received
                end = min(start + chunk_size, file_size)
                
                # Request chunk
                request = f"FILE {filename} GET START {start} END {end}"
                data_socket.sendto(request.encode('utf-8'), server_address)
                print(f"Requesting chunk: {start}-{end}")
                
                # Receive chunk
                response, _ = data_socket.recvfrom(65535)  # Increased buffer size for base64 data
                response = response.decode('utf-8')
                
                # Parse response
                parts = response.split()
                if len(parts) >= 8 and parts[0] == "FILE" and parts[2] == "OK":
                    # Extract and decode data
                    data_start = response.find("DATA ") + 5
                    encoded_data = response[data_start:]
                    chunk_data = base64.b64decode(encoded_data)
                    
                    # Write chunk to file
                    f.write(chunk_data)
                    bytes_received += len(chunk_data)
                    print(f"Received {len(chunk_data)} bytes")
                else:
                    print(f"Unexpected response: {response}")
                    break
        
        # Send close request
        close_request = f"FILE {filename} CLOSE"
        data_socket.sendto(close_request.encode('utf-8'), server_address)
        
        # Wait for close confirmation
        response, _ = data_socket.recvfrom(1024)
        response = response.decode('utf-8')
        if response == f"FILE {filename} CLOSE_OK":
            print("File transfer completed successfully")
        else:
            print("Unexpected response to close request")
            
    except Exception as e:
        print(f"Error during file transfer: {str(e)}")
    finally:
        data_socket.close()

def main():
    # Create a UDP socket
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # 直接使用 localhost 和固定端口
    server_host = 'localhost'
    server_port = 51234
    server_address = (server_host, server_port)

    try:
        # Get filename from user
        filename = input("Enter the filename to download: ")
        
        # Send DOWNLOAD request to server
        message = f"DOWNLOAD {filename}"
        client_socket.sendto(message.encode('utf-8'), server_address)
        print(f"Sent: {message}")

        # Receive response from server
        response, _ = client_socket.recvfrom(1024)
        response = response.decode('utf-8')
        print(f"Received: {response}")

        # Parse server response
        if response.startswith("OK"):
            # Extract file information from response
            parts = response.split()
            filename = parts[1]
            size = int(parts[3])
            port = int(parts[5])
            print(f"File found: {filename}")
            print(f"Size: {size} bytes")
            print(f"Port: {port}")
            
            # Start file download
            download_file(filename, server_host, port, size)
        elif response.startswith("ERR"):
            print("Error: File not found on server")

    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client_socket.close()

if __name__ == "__main__":
    main()