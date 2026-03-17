import os
import time
import requests
import json
import secrets
import sqlite_fifo
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
print(f"Uploading JSON - {datetime.now()}")

db = os.environ.get('DB_NAME')
json_table_name= os.environ.get('JSON_TABLE')
log_to_cloud_table = os.environ.get('LOG_CLOUD_TABLE')
dataposturl=os.environ.get('DATA_POST_URL')

def delete_after_this_string(input_string, string_to_delete):
    index = input_string.find(string_to_delete)

    if index != -1:
      
        modified_string = input_string[:index]
        deleted_string = input_string[index:]
    else:
    
        modified_string = input_string
        deleted_string = ""

    return modified_string, deleted_string

def get_me_uuid(file_name, mac_address, post_data):
    with open(file_name, 'r') as f:
        uuid_map = json.load(f)

    mode = uuid_map.get(mac_address, {}).get("mode", 0)
    sensor_id = uuid_map.get(mac_address, {}).get("SensorID:0")

    if mode == 0:
        prefix = sensor_id[0] if sensor_id is not None else 0
        suffix = sensor_id[1] if sensor_id is not None else 0
    elif mode == 1:
        post_data, sensor_id = delete_after_this_string(post_data, "SensorID")
        sensor_id_value = uuid_map.get(mac_address, {}).get(sensor_id)
        prefix = sensor_id_value[0] if sensor_id_value is not None else 0
        suffix = sensor_id_value[1] if sensor_id_value is not None else 0
    else:
        prefix = None
        suffix = None

    return prefix, suffix, post_data



def post_to_server(data_post):
    req_json=data_post

    headers = {'Accept':"*/*",
               'Content-type': "application/json",
               'ApiKey': secrets.token_hex(16),
               'Connection':"keep-alive"}
    print('sending data to server')
    try:
        r=requests.request("POST",dataposturl,data=req_json,headers=headers,timeout=5)
        print(req_json.replace("'",'"'))
        print(r.status_code)
        return r.status_code
        
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        return 0
    except requests.exceptions.ConnectionError as conn_err:
        print(f"Connection error occurred: {conn_err}")
        return 0
    except requests.exceptions.RequestException as req_err:
        print(f"An error occurred: {req_err}")
        return 0
    except Exception as e:
        # Catch any other unexpected exceptions
        print(f"An unexpected error occurred: {e}")
        return 0

if __name__=="__main__":

    conn_json, cursor_json = sqlite_fifo.init_db(db, json_table_name)
    conn_log_to_cloud, cursor_log_to_cloud = sqlite_fifo.init_db(
            db, log_to_cloud_table)

    while True:
        data = sqlite_fifo.peek_data(cursor_json, json_table_name)

        if data is None:
            time.sleep(0.000005)
            continue

        print(f"popped data is {data}")

        mac_address = data[:17]
        post_data = data[17:]   # <-- NOW post_data exists

        if mac_address.count(':') != 5:
            print("Invalid mac address")
            sqlite_fifo.push_data(cursor_log_to_cloud, conn_log_to_cloud, log_to_cloud_table, data)
            sqlite_fifo.pop_data(cursor_json, conn_json, json_table_name)
            continue

        with open('src/uuid.json', 'r') as f:
            uuid_map = json.load(f)

        uuid_prefix, uuid_suffix, post_data = get_me_uuid("src/uuid.json", mac_address, post_data)

        print(f"uuid_prefix is {uuid_prefix}, uuid_suffix is {uuid_suffix}")

        if uuid_prefix is None or uuid_suffix is None:
            sqlite_fifo.pop_data(cursor_json, conn_json, json_table_name)
            sqlite_fifo.push_data(
                cursor_log_to_cloud, conn_log_to_cloud, log_to_cloud_table,mac_address + "mac_not_found")
            continue

    #CLEAN + PARSE ONLY HERE
        try:
            clean = post_data
            clean = clean.replace("startjson00:00:00:00:00:00", "")
            clean = clean.split("SensorID")[0]
            clean = "{" + clean + "}"

            parsed = json.loads(clean)

        except Exception as e:
            print(f"error in json = {e}")
            sqlite_fifo.pop_data(cursor_json, conn_json, json_table_name)
            sqlite_fifo.push_data(cursor_log_to_cloud, conn_log_to_cloud, log_to_cloud_table,
            mac_address + "json_parse_error"
        )
            continue

        output_data = {
            "device_data": {
                "sensors": [
                    {
                        "uuid": uuid_prefix,
                        **parsed
                    }
                ],
                "device_uuid": uuid_suffix
            }
        }

        output_json = json.dumps(output_data, ensure_ascii=False)
        print(output_json)

        server_response = post_to_server(output_json)
        if server_response == 200:
            sqlite_fifo.pop_data(cursor_json, conn_json, json_table_name)
        else:
            print("server not responding, backing up data")
            time.sleep(0.000005)
