import paramiko
import os
class SSHTransferHandler:

    def __init__(self) -> None:
        IP_ADDRESS = '133.9.125.56'
        USER_NAME = 'yuyasato'
        PORT = 49152
        print(os.listdir("C:\\Users"))
        KEY_FILENAME = '/root/.ssh/sunrise'
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect(
                IP_ADDRESS,
               username=USER_NAME,
               key_filename=KEY_FILENAME,
               port=PORT,
               timeout=3.9)
        stdin, stdout, stderr = client.exec_command("echo Hello")
        print(stdout)