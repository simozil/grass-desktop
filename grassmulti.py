import json
import asyncio
import random
import ssl
import time
import uuid
from loguru import logger
from websockets_proxy import Proxy, proxy_connect
from colorama import init, Fore, Style
import requests
import websockets
from concurrent.futures import ThreadPoolExecutor

# Initialize colorama
init(autoreset=True)

# Function to read multiple credentials
def read_credentials(file_path):
    with open(file_path, 'r') as file:
        credentials = [line.strip().split(':') for line in file.readlines()]
    return credentials

# Function to read proxies
def read_proxies(file_path):
    with open(file_path, 'r') as file:
        proxies = [line.strip() for line in file.readlines()]
    return proxies

# Function to filter proxies
def filter_proxies(proxies):
    valid_proxies = []
    
    def check_proxy(proxy):
        ip, isp_info = get_public_ip_and_isp(proxy)
        print(ip, isp_info)
        if "Type: HOSTING" not in isp_info:
            print("Proxy is Residential")
            return proxy
        else:
            print("Proxy is Hosting, removing...")
            remove_proxy_from_file(proxy, 'proxy.txt')
            return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(check_proxy, proxies)
    
    valid_proxies = [proxy for proxy in results if proxy is not None]
    return valid_proxies

# Function to remove proxy from file
def remove_proxy_from_file(proxy, file_path):
    with open(file_path, 'r') as file:
        lines = file.readlines()
    with open(file_path, 'w') as file:
        for line in lines:
            if line.strip() != proxy:
                file.write(line)

# Function to login and get user info for each account
def login_and_get_user_info(username, password, proxy):
    login_url = 'https://api.getgrass.io/login'
    headers = {
        'accept': '*/*',
        'content-type': 'text/plain;charset=UTF-8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    }
    data = json.dumps({"username": username, "password": password})
    
    max_retries = 5
    backoff_factor = 2
    for attempt in range(max_retries):
        try:
            response = requests.post(login_url, headers=headers, data=data, proxies={"http": proxy, "https": proxy})
            response.raise_for_status()
            response_data = response.json()
            access_token = response_data['result']['data']['accessToken']
            user_id = response_data['result']['data']['userId']

            # Retrieve additional user info
            user_info_url = 'https://api.getgrass.io/retrieveUser'
            headers['authorization'] = access_token
            response = requests.get(user_info_url, headers=headers, proxies={"http": proxy, "https": proxy})
            response.raise_for_status()
            user_info = response.json()['result']['data']
            total_points = user_info['totalPoints']
            formatted_points = f"{total_points / 1000:.1f}K" if total_points < 1000000 else f"{total_points / 1000000:.1f}M"
            print(Fore.GREEN + f"Username: {username} | Total Points: {formatted_points}")
            print(Fore.GREEN + f"Starting [ Sirkel Generous ] Grass Bot for {username}...")
            time.sleep(2)
            return user_id
        except requests.exceptions.RequestException as e:
            logger.error(f"Attempt {attempt + 1} failed for {username}: {e}")
            if attempt < max_retries - 1:
                sleep_time = backoff_factor ** attempt
                logger.info(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                logger.error(f"Max retries reached for {username}. Exiting.")
                raise

# Function to get public IP and ISP
def get_public_ip_and_isp(proxy):
    attempts = 0
    while attempts < 5:
        try:
            response = requests.get('https://api.ipapi.is/', proxies={"http": proxy, "https": proxy})
            data = response.json()
            ip = data['ip']
            isp = data['asn']['descr']
            country = data['location']['country']
            isp_type = data['asn']['type'].upper()
            return ip, f"{isp} | {Fore.WHITE} {country} | {Fore.CYAN+Style.BRIGHT}Type: {isp_type}"
        except Exception as e:
            attempts += 1
            if attempts >= 5:
                return "Unavailable", "Unavailable"
            time.sleep(1)

# Function to connect to WebSocket for each user
async def connect_to_wss(socks5_proxy, user_id, device_status):
    device_id = str(uuid.uuid3(uuid.NAMESPACE_DNS, socks5_proxy))
    ip, isp = get_public_ip_and_isp(socks5_proxy)
    device_status[device_id] = {"ping_count": 0, "ip": ip, "isp": isp, "status": "Connecting to web sockets"}
    print_status(device_status)

    while True:
        try:
            custom_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
            }
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            uri = "wss://proxy2.wynd.network:4650/"
            server_hostname = "proxy2.wynd.network"
            proxy = Proxy.from_url(socks5_proxy)
            
            async with proxy_connect(uri, proxy=proxy, ssl=ssl_context, server_hostname=server_hostname,
                                     extra_headers=custom_headers) as websocket:
                device_status[device_id]["status"] = "Connected"
                print_status(device_status)

                async def send_ping():
                    try:
                        while True:
                            ip, isp = get_public_ip_and_isp(socks5_proxy)
                            device_status[device_id]["ip"] = ip
                            device_status[device_id]["isp"] = isp
                            print_status(device_status)

                            send_message = json.dumps(
                                {"id": str(uuid.uuid4()), "version": "1.0.0", "action": "PING", "data": {}})
                            await websocket.send(send_message)
                            device_status[device_id]["ping_count"] += 1
                            device_status[device_id]["status"] = f"{Fore.YELLOW+Style.BRIGHT}Sending Ping"
                            print_status(device_status)
                            for i in range(60, 0, -1):
                                device_status[device_id]["status"] = f"{Fore.GREEN+Style.BRIGHT}Ping Success. Next in {i} seconds"
                                print_status(device_status)
                                await asyncio.sleep(1)
                    except websockets.exceptions.ConnectionClosedError as e:
                        device_status[device_id]["status"] = f"{Fore.RED+Style.BRIGHT}Connection closed error: {e}"
                        device_status[device_id]["ping_count"] = 0
                        print_status(device_status)
                        await asyncio.sleep(5)
                        return

                await asyncio.sleep(1)
                asyncio.create_task(send_ping())

                while True:
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=500)
                        message = json.loads(response)
                        if message.get("action") == "AUTH":
                            auth_response = {
                                "id": message["id"],
                                "origin_action": "AUTH",
                                "result": {
                                    "browser_id": device_id,
                                    "user_id": user_id,
                                    "user_agent": custom_headers['User-Agent'],
                                    "timestamp": int(time.time()),
                                    "device_type": "extension",
                                    "version": "4.26.2",
                                    "extension_id": "ilehaonighjijnmpnagapkhpcdbhclfg"
                                }
                            }
                            device_status[device_id]["status"] = f"{Fore.GREEN+Style.BRIGHT}Received AUTH Response"
                            print_status(device_status)
                            await websocket.send(json.dumps(auth_response))
                            device_status[device_id]["status"] = f"{Fore.YELLOW+Style.BRIGHT}Sending Auth"
                            print_status(device_status)

                        elif message.get("action") == "PONG":
                            device_status[device_id]["status"] = f"{Fore.GREEN+Style.BRIGHT}Received PONG"
                            print_status(device_status)
                            pong_response = {"id": message["id"], "origin_action": "PONG"}
                            await websocket.send(json.dumps(pong_response))
                    except asyncio.TimeoutError:
                        device_status[device_id]["status"] = f"{Fore.RED+Style.BRIGHT}Timeout while waiting for message"
                        device_status[device_id]["ping_count"] = 0
                        print_status(device_status)
                    except websockets.exceptions.ConnectionClosedError as e:
                        device_status[device_id]["status"] = f"{Fore.RED+Style.BRIGHT}Connection closed error: {e}"
                        device_status[device_id]["ping_count"] = 0
                        print_status(device_status)
                        break
                    except Exception as e:
                        device_status[device_id]["status"] = f"{Fore.RED+Style.BRIGHT}Error receiving message: {e}"
                        print_status(device_status)

        except Exception as e:
            device_status[device_id]["status"] = f"{Fore.RED+Style.BRIGHT}Connection error: {e}"
            print_status(device_status)
            await asyncio.sleep(5)

# Function to print device status
def print_status(device_status):
    print("Device Status:")
    for device_id, status in device_status.items():
        print(f"{device_id} | {status['ip']} | {status['isp']} | {status['ping_count']} | {status['status']}")
    print("-" * 80)

# Main function to handle multiple accounts
async def main():
    proxies = read_proxies('proxy.txt')
    credentials = read_credentials('data.txt')
    check_proxy = input("Do you want to check proxies? (y/n): ").strip().lower()

    if check_proxy == 'y':
        valid_proxies = filter_proxies(proxies)
        if not valid_proxies:
            print("No valid proxies found.")
            return
    else:
        valid_proxies = proxies

    device_status = {}

    # Loop through each account and assign a proxy
    tasks = []
    for i, (username, password) in enumerate(credentials):
        if i >= len(valid_proxies):
            print("Not enough proxies for each account.")
            break
        proxy = valid_proxies[i]
        user_id = login_and_get_user_info(username, password, proxy)
        tasks.append(asyncio.create_task(connect_to_wss(proxy, user_id, device_status)))

    # Wait for all tasks to complete
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    asyncio.run(main())
