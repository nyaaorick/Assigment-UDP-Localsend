# UDP-Localsend

**Author:** JUNYAO SHI  
**ID:** 20233006416  

## Description

All file operations are contained within specific directories: `serverfile` on the server and `client_files` on the client.


## How to Use


## Examples

**start server**

```bash
python3 server.py

or

python3 server.py 8888
```

**start client**

```bash

python3 client.py localhost 8888

or

python3 client.py
in this case you will need enter host next step
```

## Command List

The client accepts the following commands:

| Command           | Description                                                                  |
| :---------------- | :--------------------------------------------------------------------------- |
| `cd <folder>`     | Change to the specified directory on the server (e.g., `cd folder1`).        |
| `cd ..`           | Go back to the parent directory on the server.                               |
| `<filename>`      | Download a specific file by entering its name (e.g., `1.mp4`).               |
| `all`             | Download all files in the current remote directory.                          |
| `upload <filename>` | Upload a file from your local machine to the server's current directory.   |
| `kill`            | **DANGER:** Deletes **every file** on the folder.                            |
| `supload`         | super upload make you upload a folder!                                       |
| `(press enter)`   | Exit the client application.                                                 |


