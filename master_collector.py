import datetime,time
#import minimalmodbus
import psutil
import sqlite_fifo
import subprocess
#import serial
#from serial.rs485 import RS485, RS485Settings
from struct import unpack
#import serial.tools.list_ports
#import board
#import adafruit_dht
import Adafruit_DHT
from smbus2 import SMBus
from datetime import datetime, timedelta
from pymodbus.client import ModbusTcpClient
from pymodbus.pdu import ModbusPDU
from pymodbus.framer import FramerType
from pymodbus.exceptions import ModbusIOException, ModbusException, ConnectionException
from dotenv import load_dotenv
import threading,socket,yaml
import coloredlogs,logging,os


#TAG for troubleshooting --> where the error orginated.
tag ="[mod_data_collector.py]"

coloredlogs.install(level='DEBUG', logger=logging.getLogger("mod_data_collector"),fmt='[mod_data_collector] : %(asctime)s %(levelname)s %(message)s')
log = logging.getLogger("mod_data_collector")
load_dotenv()
print(f"{tag} : Started Data Collection Modbus - {datetime.now()}")
#.env
pisystem = str(os.environ.get('PI_SYSTEM'))
reading_intervl=int(os.environ.get('DATA_INTERVAL',60))  #data interval
db = str(os.environ.get('DB_NAME'))
table_name = os.environ.get('RAW_DATA_TABLE')

# Port for RS485
#PORT_RS485 = '/dev/ttyUSB0'
#PORT_RS485 = '/dev/ttyAMA1'

#TCP PORT
PORT_TCP=502
# json directory
parameter=""
json_list=[]

# Register for Charge
CHARGE_REG = 0x0D
I2C_BUS = 4
DEVICE_ADDR = 0x0B

# Endian flags
BIG_ENDIAN = 0
LITTLE_ENDIAN = 1
BYTE_SWAP = 2
WORD_SWAP = 3
WORD_BYTE_SWAP = 4

hr = "[ HOLDING REGISTER ]"
ir = "[ INPUT REGISTER ]"
co = "[ COIL STATUS ]"

#####################################ERROR CODE HANDLING####################################################
# Error Codes and Lookup Table
error_codes = {
    "ER01": lambda a: a == 0,
    "ER04": lambda a: a > 2 or a < -2,
    "ER03": lambda a: a == 32766,
    "ER06": lambda a: a == -32768,
    "ER07": lambda a: a == 32752,
    "ER08": lambda a: a == 32768,
    "ER10": lambda a: a < 0,
    "ER05": lambda a: isinstance(a, float) and (a - int(a)) != 0,
    "ER14": lambda a: a > 2500
}

lookup_table = {
    'json_group1': [
        ((1, 37), ["E"], ["ER01", "ER10", "ER03"]),
        ((43, 49), ["E"], ["ER01", "ER10", "ER03"]),
        ((38, 42), ["E"], ["ER03", "ER04"]),
        ((50, 246), ["E"], ["ER03", "ER10"])
    ],
    'json_group2': [
        ((41, 45), ["T"], ["ER03", "ER04", "ER06", "ER07", "ER08"]),
        ((161, 165), ["T"], ["ER03", "ER04", "ER06", "ER07", "ER08"]),
        ((81, 85), ["T"], ["ER03", "ER04", "ER06", "ER07", "ER08"]),
        ((178,178), ["T"], ["ER03", "ER04", "ER06", "ER07", "ER08"]),
        ((179,179), ["T"], ["ER03", "ER04", "ER06", "ER07", "ER08"])
    ],
    'json_group3': [
        ((1,28), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((29,39), ["T"], ["ER03"]),
        ((44,61), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((63,68), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((69,80), ["T"], ["ER03"]),
        ((86,109), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((136,137), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((151,151), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((155, 156), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((166, 176), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((181, 192), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((199, 218), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((217, 226), ["T"], ["ER01", "ER03", "ER06", "ER07", "ER08", "ER10"])
    ],
    'json_group4': [
        ((40,40), ["T"], ["ER10"]),
        ((62,62), ["T"], ["ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((135,135), ["T"], ["ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((160,160), ["T"], ["ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((177,177), ["T"], ["ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((142,150), ["T"], ["ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((152, 160), ["T"], ["ER03", "ER06", "ER07", "ER08", "ER10"]),
        ((180,180), ["T"], ["ER03", "ER06", "ER07", "ER08", "ER10"])
    ],
    'json_OLTC': [
        ((138,138), ["T"], ["ER01", "ER05", "ER10"])
    ]
}

# Fn to determine the group, sol_name(s), and applicable error codes for the given CH_NO and sol_name
def get_error_codes_for_CH_NO_and_sol_name(CH_NO, sol_name):
    for group, ranges in lookup_table.items():
        for r, sol_names, error_list in ranges:
            if isinstance(r, tuple):
                if r[0] <= CH_NO <= r[1] and sol_name in sol_names:
                    return group, error_list
            elif isinstance(r, int) and r == CH_NO and sol_name in sol_names:
                return group, error_list
    return None, []

# Fn to handle the error from respective code
def handle_error(a, CH_NO, sol_name):
    CH_group, applicable_error_codes = get_error_codes_for_CH_NO_and_sol_name(CH_NO, sol_name)

    if not CH_group or not applicable_error_codes:
        return a

    for error_code in applicable_error_codes:
        if error_codes[error_code](a):
            return f'"{error_code}"'
    return a

def packet_logger(sending: bool, packet: bytes) -> bytes:
    direction = "TX" if sending else "RX"
    hex_data = packet.hex(' ')
    log.debug(f"[PACKET {direction}] {hex_data}")
    return packet

def pdu_logger(sending: bool, pdu: ModbusPDU) -> ModbusPDU:

    direction = "TX" if sending else "RX"

    hex_pdu = pdu.encode().hex(' ')
    log.debug(f"[PDU {direction}] Func={pdu.function_code} Data={hex_pdu}")
    return pdu

def connect_logger(connected: bool) -> None:
    state = "CONNECTED" if connected else "DISCONNECTED"
    log.debug(f"[CONNECT] {str(state)}")

def get_battery_percentage(bus, addr, reg):
    charge = "\"ER03\""
    try:
        charge = bus.read_byte_data(addr, reg)
        print(f"{tag} : Battery Charge % : {charge}%")
        return charge
    except:
        charge = "\"ER03\""
        return charge

def get_temp_humidity_orange():
    try:
        output = subprocess.check_output(['node_dht11.js'])
        output = output.decode('utf-8').strip()
        temperature_str = output.split('celsius: ')[1].split(' ')[0]
        humidity_str = output.split('humidity: ')[1]
        return temperature_str,humidity_str
    except:
        temperature = "\"ER03\""
        humidity = "\"ER03\""
        return temperature,humidity

def get_temp_humidity_raspberry():
    temperature = "\"ER03\""
    humidity = "\"ER03\""
    try:
        dhtDevice = adafruit_dht.DHT11(board.D4)
        temperature_c = dhtDevice.temperature
        temperature_f = temperature_c * (9 / 5) + 32
        humidity = dhtDevice.humidity
        return str(temperature_c), str(humidity)
    except Exception as e:
        print(f"{tag} : An error occurred: {str(e)}")
        temperature = "\"ER03\""
        humidity = "\"ER03\""
        return temperature, humidity
    finally:
        dhtDevice.exit()

def get_temp_humidity_raspberry1():
    temperature = "\"ER03\""
    humidity = "\"ER03\""
    try:
        sensor = Adafruit_DHT.DHT11
        pin = 4
        humidity, temperature = Adafruit_DHT.read_retry(sensor, pin)
        if humidity is not None and temperature is not None:
            temperature_f = temperature * (9 / 5) + 32
            print(f"Temperature: {temperature} C / {temperature_f} F, Humidity: {humidity}%")
        else:
            print("Failed to retrieve data from the sensor")
            temperature = "\"ER03\""
            humidity = "\"ER03\""
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        temperature = "\"ER03\""
        humidity = "\"ER03\""
    return str(temperature), str(humidity)


def handle_modbus_tcp_error(data_reader, e, address, tag="[MODBUS-TCP]"):


    if isinstance(e, ConnectionException):
        data_reader.instrument._print_debug(
            f"{tag} : No response from slave at address {address}, Reason: {e}"
        )
        return "\"ER19\""  # No response from slave

    elif isinstance(e, ModbusIOException):
        data_reader.instrument._print_debug(
            f"{tag} : Illegal request for address {address}, Reason: {e}"
        )
        return "\"ER18\""  # Illegal request (mapped from IO error)

    elif isinstance(e, ModbusException):
        data_reader.instrument._print_debug(
            f"{tag} : Slave device busy on address {address}, Reason: {e}"
        )
        return "\"ER16\""  # Slave busy

    elif isinstance(e, TimeoutError) or isinstance(e, socket.timeout):
        data_reader.instrument._print_debug(
            f"{tag} : Timeout waiting for response from address {address}, Reason: {e}"
        )
        return "\"ER19\""  # "no response"

    elif isinstance(e, ConnectionResetError):
        data_reader.instrument._print_debug(
            f"{tag} : Master reported issue on address {address}, Reason: {e}"
        )
        return "\"ER17\""  # Master reported issue

    else:
        data_reader.instrument._print_debug(
            f"{tag} : Communication error with address {address}, Reason: {e}"
        )
        return "\"ER15\""  # General communication error

def get_mac_address(interface):
    addresses = psutil.net_if_addrs()
    mac_address = addresses[interface][0].address
    return mac_address

#coil status label mapping
def bool_to_label(value: bool) -> str:
    return "OPERATED" if value else "HEALTHY"
##################################TCP-IP####################################################
class ModbusTCPReader:
    def __init__(self, host, port=PORT_TCP, timeout=0.3):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.client = None

    def connect(self):
        try:
            self.client = ModbusTcpClient(
                host=self.host,
                port=self.port,
                timeout=self.timeout,
                retries=0,
                framer=FramerType.SOCKET,
                trace_packet=packet_logger,
                trace_pdu=pdu_logger,
                trace_connect=connect_logger
            )
            if not self.client.connect():
                raise ConnectionError(f"Cannot connect to {self.host}:{self.port}")
            log.info(f"Connected to {self.host}:{self.port}")

        except Exception as e:
            time.sleep(0.2)
            log.error(f"Connection error to {self.host}:{self.port} - {e}")
            raise

    def close(self):
        if self.client:
            time.sleep(1)
            self.client.close()

    def swap_bytes(self, value):
        return int.from_bytes(value.to_bytes(2, "big")[::-1], "big")

    def decode_registers(self, registers, data_type, endian_flag):
        if not registers:
            log.warning("[decode_registers] Empty register list received")
            return None

        # 16-bit values
        if data_type in (1, 2):
            if len(registers) < 1:
                log.error(f"[decode_registers] Not enough registers for 16-bit data_type {data_type}: {registers}")
                return None
            value = registers[0]
            if data_type == 2:  #  signed int16
                return unpack(">h", value.to_bytes(2, "big"))[0]
            return value # unsigned int16

        # 32-bit values
        if data_type in (3, 4) and len(registers) >= 2:

            reg1, reg2 = registers[0], registers[1]

            # Apply endianness transformation
            if endian_flag == BIG_ENDIAN: # ABCD
                pass
            elif endian_flag == WORD_SWAP: #CDAB
                reg1,reg2 = reg2, reg1
            elif endian_flag == LITTLE_ENDIAN:  #DCBA
                reg1, reg2 = self.swap_bytes(reg2), self.swap_bytes(reg1)
            elif endian_flag == BYTE_SWAP: #BADC
                reg1, reg2 = self.swap_bytes(reg1), self.swap_bytes(reg2)
            elif endian_flag ==  WORD_BYTE_SWAP: ## CDAB + BADC
                reg1, reg2 = self.swap_bytes(reg2), self.swap_bytes(reg1)

            raw32 = (reg1 << 16) | reg2

            if data_type == 3:  # float32
                return unpack(">f", raw32.to_bytes(4, "big"))[0]
            else:  # int32
                return unpack(">i", raw32.to_bytes(4, "big"))[0]
        else:
            log.error(f"[decode_registers] Unsupported data_type {data_type}")
        return None

    def read_value(self, slave_id, address, f_code, data_type, endian, bytes_to_read=2):
        try:
            if not self.client or not self.client.is_socket_open():
                self.connect()


            valid_fc_map = {1: "Coil", 3: "Holding", 4: "Input"}  #dicrectory to check valid function code
            if f_code not in valid_fc_map:
                log.error(f"[Slave {slave_id}] Invalid function code: {f_code}")
                return "\"ER18\""

            # Coil reading
            if f_code == 1 or data_type == 5: #function_code 1:coil_status , data-type=5 is bool/int-from .yaml
                coil_header = co.center(50)
                log.info(coil_header)
                count = 1 #default count/bytes=1;
                response = self.client.read_coils(address=address, count=count, slave=slave_id)
                time.sleep(0.2)
                if response.isError() or not response.bits:
                    log.error(f"No response from slave ID: {slave_id} coil_address: {address}")
                    return "\"ER19\""
                value = response.bits[0] if response.bits else False
                status = f"\"{bool_to_label(value)}\""
                log.info(f"[Slave ID {slave_id}] Bytes_to_read:{count} Coil_address: {address} -→ {str(status)}")
                return status

            #check data type for register:
            if data_type not in (1,2,3,4):
                log.error(f"[Slave {slave_id}] Invalid data_type {data_type}  for holding register at {address}")
                return "\"ER99\"" #invalid data_type

            #holding and input-registers
            count = 1 if data_type in (1, 2) else 2 #count=1 (int),(unsigint) count=2 (float),(double)
            if f_code == 3: #[HR]
                holding_header = hr.center(50)
                log.info(holding_header)
                response = self.client.read_holding_registers(address=address, count=count, slave=slave_id)
                time.sleep(0.1)
            elif f_code == 4: #[IR]
                input_header = ir.center(50)
                log.info(input_header)
                response = self.client.read_input_registers(address=address, count=count, slave=slave_id)
                time.sleep(0.1)
            else:
                log.error(f"[Slave {slave_id}] Invalid function code {f_code} for register read at {address}")
                return "\"ER98\""

            #check response
            if response.isError() or not hasattr(response, "registers") or not response.registers:
                return "\"ER19\""
            
            log.debug(f"RX BYTES (PDU): {response.encode().hex(' ')}")
            log.debug(f"Raw registers: {response.registers}")
            value = self.decode_registers(response.registers, data_type, endian)
            log.info(f"[Slave ID {slave_id}] Bytes_to_read:{count} Register_address: {address} -→ {value}")
            return value if value is not None else "\"ER19\""

        except Exception as e:
            print(f"{tag} : Modbus TCP error for slave {slave_id}, address {address}: {e}")
            return "\"ER15\""

# Load the YAML configuration file
temperature_key='136'
humidity_key='137'
battery_key='135'


# Main function
if __name__=="__main__":
    with open('gateway.yml', 'r') as file:
        config = yaml.safe_load(file)

    conn_raw, cursor_raw = sqlite_fifo.init_db(db, table_name) #creat database

    # Create TCP readers for each slave
    tcp_readers = {}
    for slave_config in config['slaves']:
        communication_settings = slave_config['communication']
        ip_addr = communication_settings.get('IP_address')
        if ip_addr:
            tcp_readers[ip_addr] = ModbusTCPReader(host=ip_addr)
            try:
                tcp_readers[ip_addr].connect()
            except Exception as e:
                print(f"{tag} : Failed to connect to {ip_addr}: {e}")

    while True:
        start_time = datetime.now()
        nxt_reading_time = start_time + timedelta(seconds=reading_intervl) ####interval for reading

        for slave_config in config['slaves']:
            ip_addr = slave_config['communication'].get('IP_address')

            if not ip_addr or ip_addr not in tcp_readers:
                print(f"{tag} : Skipping unavailable slave: {ip_addr}")
                continue

            tcp_reader = tcp_readers[ip_addr]
            #sensors = slave_config['sensors']
            for sensor in slave_config['sensors']:
                now = datetime.now()
                rounded_seconds = now.strftime("%Y-%m-%d %H:%M:%S")
                time_string="\"created_at\":"+"\""+str(rounded_seconds)+"\""
                slave_address=sensor['slave_address']
                sensor_id = sensor['id']
                registers = sensor['registers']
                header = "startjson00:00:00:00:00:00"
                footer1="end"
                footer2=f"SensorID:{sensor_id}end"
                print(f"{tag} :- Sensor ID: {sensor_id} slave-id {slave_address}")

                #parameter = "" #rest per sensor
                #registers_sorted = sorted(registers, key=lambda r: int(r['name']))
                for register in registers:
                    print()
                    print("<###########################- REGISTER COUNT-###########################>")
                    address = register['address']
                    name = str(register['name']).zfill(2)
                    bytes_to_read = register['bytes']
                    data_type=register['data_type']
                    endian=register['endian']
                    f_code=register['function_code']
                    solution_name=register['solution']

                    try:

                        data = tcp_reader.read_value(
                        slave_id=slave_address,
                        address=address,
                        f_code=f_code,
                        data_type=data_type,
                        endian=endian,
                        bytes_to_read=bytes_to_read
                       # name = solution_name + name
                       )

                        if isinstance(data, float) and math.isnan(data):
                            data = "\"ER91\""
                        elif not isinstance(data, (int, float, str)):
                            data = "\"ER15\""   # Catch anything weird
                    except Exception as e:
                        time.sleep(0.07)
                        data = handle_modbus_tcp_error(tcp_reader, e, address, tag=tag)

                    print(f"{tag} : Data after Error check is {data}")
                    #parameter += "\""+solution_name+name+"\":"+str(data)+","
                    print(f"{tag} Register - Address: {address}, Name: {name}, Bytes to Read: {bytes_to_read} Data: {data}")
                    if solution_name and name:
                       parameter += f'"{solution_name}{name}":{data},'
                    time.sleep(0.05)
                # Handle sensor data
                if sensor_id != 0:
                    footer=f"SensorID:{sensor_id}end"  #footer2
                    post_data=header+parameter+time_string+footer
                    assert isinstance(post_data, str)
                    print(f"SensorID {sensor_id},[PEEk]{post_data}")
                    time.sleep(0.1)
                    json_list.append(post_data)
                    parameter=""
                else:
                    pass

            if sensor_id == 0:
                temperature,humidity=get_temp_humidity_raspberry1()

                with SMBus(I2C_BUS) as bus:
                    charge = get_battery_percentage(bus, DEVICE_ADDR, CHARGE_REG)
                parameter=parameter+"\""+solution_name+temperature_key+"\":"+temperature+","
                parameter=parameter+"\""+solution_name+humidity_key+"\":"+humidity+","
                # For Battery percentage
                parameter=parameter+"\""+solution_name+battery_key+"\":"+str(charge)+","
                footer="end" #footer1
               #footer=f"SensorID:{sensor_id}end"   #footer2
                parameter = parameter.rstrip(",")
                post_data= header+parameter+","+time_string+footer
                assert isinstance(post_data, str)
                print(f"Sensor ID {sensor_id}: [PEEK]{post_data}")

                time.sleep(0.1)
                json_list.append(post_data)
                parameter=""

    #json creation:
                #print(f"SensorID {sensor_id},[PEEk]{post_data}")
                # Push data to database
                while len(json_list) > 0:
                    popped_data = json_list.pop(0)
                    sqlite_fifo.push_data(cursor_raw, conn_raw, table_name, popped_data) #push in sqlite3
                    time.sleep(0.03)
                    print(f"[POP] Popped data:- {popped_data}")
            # Serial trigger handling (if needed)
        while datetime.now() < nxt_reading_time:
            time.sleep(0.05)
