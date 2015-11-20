#!/usr/bin/env python
# 

import numpy
import binascii
import sys
from datetime import datetime, timedelta
import threading
from gnuradio import gr

class mac(gr.basic_block):
    # The numbers represents bytes location/width
    MAC_FRAME_MFH_WIDTH = 2
    MAC_FRAME_MFH_OFFSET = 0
    MAC_FRAME_CONFOUNDER_WIDTH = 4
    MAC_FRAME_ODA_WIDTH = 6
    MAC_FRAME_OSA_WIDTH = 6
    MAC_FRAME_ETHERTYPE_OR_LENGTH_WIDTH = 2
    MAC_FRAME_ICV_WIDTH = 4
    MAC_FRAME_OVERHEAD = MAC_FRAME_MFH_WIDTH + MAC_FRAME_ODA_WIDTH + MAC_FRAME_OSA_WIDTH + MAC_FRAME_ETHERTYPE_OR_LENGTH_WIDTH + MAC_FRAME_ICV_WIDTH

    MGMT_MMV_WIDTH = 8
    MGMT_MMV_OFFSET = 0
    MGMT_MMTYPE_WIDTH = 16
    MGMT_FMI_WIDTH = 8

    MGMT_MMTYPE_CM_CHAN_EST_ID = 0x6014
    MGMT_CM_CHAN_EST_MAX_FL_WIDTH = 16
    MGMT_CM_CHAN_EST_MAX_FL_OFFSET = 0
    MGMT_CM_CHAN_EST_RIFS_WIDTH = 8
    MGMT_CM_CHAN_EST_RIFS_OFFSET = 16
    MGMT_CM_CHAN_EST_RIFS_TWOSYM_WIDTH = 8
    MGMT_CM_CHAN_EST_RIFS_TWOSYM_OFFSET = 24
    MGMT_CM_CHAN_EST_G2SYM_WIDTH = 8 
    MGMT_CM_CHAN_EST_G2SYM_OFFSET = 32
    MGMT_CM_CHAN_EST_RESPT_WIDTH = 8
    MGMT_CM_CHAN_EST_RESPT_OFFSET = 40
    MGMT_CM_CHAN_EST_MAXTM_WIDTH = 8
    MGMT_CM_CHAN_EST_MAXTM_OFFSET = 48
    MGMT_CM_CHAN_EST_CP_TMI_WIDTH = 8
    MGMT_CM_CHAN_EST_CP_TMI_OFFSET = 56
    MGMT_CM_CHAN_EST_SCL_CP_WIDTH = 8
    MGMT_CM_CHAN_EST_SCL_CP_OFFSET = 64
    MGMT_CM_CHAN_EST_SCL_CFP_WIDTH = 8
    MGMT_CM_CHAN_EST_SCL_CFP_OFFSET = 72
    MGMT_CM_CHAN_EST_NTMI_WIDTH = 8
    MGMT_CM_CHAN_EST_NTMI_OFFSET = 80
    MGMT_CM_CHAN_EST_TMI_WIDTH = 8
    MGMT_CM_CHAN_EST_NINT_WIDTH = 8
    MGMT_CM_CHAN_EST_ET_WIDTH = 16
    MGMT_CM_CHAN_EST_INT_TMI_WIDTH = 8
    MGMT_CM_CHAN_EST_NEW_TMI_WIDTH = 8
    MGMT_CM_CHAN_EST_CPF_WIDTH = 8
    MGMT_CM_CHAN_EST_FECTYPE_WIDTH = 8
    MGMT_CM_CHAN_EST_GIL_WIDTH = 8
    MGMT_CM_CHAN_EST_CBD_ENC_WIDTH = 8
    MGMT_CM_CHAN_EST_CBD_LEN_WIDTH = 16
    MGMT_CM_CHAN_EST_CBD_WIDTH = 4
    MGMT_CM_CHAN_EST_PAD_WIDTH = 4

    PHY_BLOCK_HEADER_WIDTH = 4
    PHY_BLOCK_BODY_OFFSET = 4
    PHY_BLOCK_PBCS_WIDTH = 4 

    # The numbers represents bits location/width
    PHY_BLOCK_HEADER_SSN_WIDTH = 16
    PHY_BLOCK_HEADER_SSN_OFFSET = 0
    PHY_BLOCK_HEADER_MFBO_WIDTH = 9
    PHY_BLOCK_HEADER_MFBO_OFFSET = 16
    PHY_BLOCK_HEADER_VPBF_WIDTH = 1
    PHY_BLOCK_HEADER_VPBF_OFFSET = 25
    PHY_BLOCK_HEADER_MMQF_WIDTH = 1
    PHY_BLOCK_HEADER_MMQF_OFFSET = 26
    PHY_BLOCK_HEADER_MMBF_WIDTH = 1
    PHY_BLOCK_HEADER_MMBF_OFFSET = 27
    PHY_BLOCK_HEADER_OPSF_WIDTH = 1
    PHY_BLOCK_HEADER_OPSF_OFFSET = 28

    MAX_SEGMENTS = 3 # max number of segments (PHY blocks) in one MAC frames
    MAX_FRAMES_IN_BUFFER = 10 # max number of MAC frames in tx buffer
    rx_incomplete_frames = {}
    tx_frames_buffer = {}
    tx_frames_in_buffer = 0
    last_ssn = -1 # track last ssn received
    last_sound_frame = datetime.min # last time a sound frame was transmitted
    last_frame_blocks_error = [] # list of last received frame blocks error
    last_frame_n_blocks = 0 # number of PHY blocks in last send frame
    sound_frame_rate = 1 # minimum time in seconds between sounds frames
    sack_timeout = 0.5 # minimum time in seconds to wait for sack
    state_waiting_for_app, state_sending_sof_sound, state_sending_sack, state_waiting_for_sack, state_waiting_for_sof = range(5)
    transmission_queue_is_full = False
    sack_timer = None
    """
    docstring for block mac
    """
    def __init__(self, device_addr, master, robo_mode, modulation, debug):
        gr.basic_block.__init__(self,
            name="mac",
            in_sig=[],
            out_sig=[])
        self.message_port_register_out(gr.pmt.to_pmt("phy out"))
        self.message_port_register_in(gr.pmt.to_pmt("phy in"))
        self.message_port_register_out(gr.pmt.to_pmt("app out"))
        self.message_port_register_in(gr.pmt.to_pmt("app in"))
        self.set_msg_handler(gr.pmt.to_pmt("app in"), self.app_in_handler)
        self.set_msg_handler(gr.pmt.to_pmt("phy in"), self.phy_in_handler)
        self.device_addr = bytearray(''.join(chr(x) for x in device_addr))
        self.debug = debug
        self.is_master = master;
        if self.is_master: 
            self.name = "MAC (master)"
            self.state = self.state_waiting_for_app
            self.modulation = modulation
            self.robo_mode = robo_mode
        else: 
            self.name = "MAC (slave)"
            self.state = self.state_waiting_for_sof

    def app_in_handler(self, msg):
        if gr.pmt.is_pair(msg):
            if gr.pmt.is_u8vector(gr.pmt.cdr(msg)) and gr.pmt.is_dict(gr.pmt.car(msg)):
                payload = bytearray(gr.pmt.u8vector_elements(gr.pmt.cdr(msg)))
                if self.debug: print self.name + ": state = " + str(self.state) + ", received payload from APP, size = " + str(len(payload)) + ", frames in buffer = " + str(self.tx_frames_in_buffer)
                if self.tx_frames_in_buffer < self.MAX_FRAMES_IN_BUFFER:
                    dict = gr.pmt.to_python(gr.pmt.car(msg))
                    dest = bytearray(dict["dest"])
                    mac_frame = self.create_mac_frame(dest, payload, False)
                    self.submit_mac_frame(mac_frame, dest)
                    if not self.transmission_queue_is_full:
                        self.send_status_to_app()
                    if self.state == self.state_waiting_for_app: self.send_sof_to_phy()
                else :
                    sys.stderr.write (self.name + ": state = " + str(self.state) + ", buffer is full, dropping frame from APP\n")
                    if self.debug: print self.name + ": state = " + str(self.state) + ", buffer is full, dropping frame from APP"

    def phy_in_handler(self, msg):
        if gr.pmt.is_pair(msg):
            cdr = gr.pmt.cdr(msg)
            car = gr.pmt.car(msg)
            if gr.pmt.is_symbol(car) and gr.pmt.is_dict(cdr):
                msg_id = gr.pmt.to_python(car)
                dict = gr.pmt.to_python(cdr)
                if msg_id == "PHY-RXEND":
                    if self.debug: print self.name + ": state = " + str(self.state) + ", received PHY-RXEND from PHY"
                    if self.state == self.state_waiting_for_sack:
                        self.send_sof_to_phy()
                        self.send_receive_to_phy()
                    elif self.state ==  self.state_waiting_for_sof:
                        self.send_sack_to_phy()
                        self.send_receive_to_phy()
                elif msg_id == "PHY-RXSOF":
                    if self.debug: print self.name + ": state = " + str(self.state) + ", received MPDU (SOF) from PHY"
                    payload = bytearray(dict["payload"].tolist())
                    self.last_frame_blocks_error = self.parse_mpdu_payload(payload)
                elif msg_id == "PHY-RXSACK":
                    if self.debug: print self.name + ": state = " + str(self.state) + ", received PHY-RXSACK from PHY"
                    if self.sack_timer:
                        self.sack_timer.cancel()
                        self.sack_time = None
                    sackd = dict["sackd"].tolist();
                    n_errors = self.parse_sackd(dict["sackd"])
                    if (n_errors): sys.stderr.write(self.name + ": state = " + str(self.state) + ", SACK indicates " + str(n_errors) + " blocks error\n")
                elif msg_id == "PHY-RXSOUND":
                    if self.debug: print self.name + ": state = " + str(self.state) + ", received PHY-RXSOUND from PHY"
                elif msg_id == "PHY-TXEND":
                    if self.debug: print self.name + ": state = " + str(self.state) + ", received PHY-TXEND from PHY"
                    if self.state == self.state_sending_sof_sound or self.state == self.state_sending_sof_sound:
                        self.state = self.state_waiting_for_sack
                        self.start_sack_timer();

                    elif self.state == self.state_sending_sack:
                        self.state = self.state_waiting_for_sof

    def sack_timout_callback(self):
        sys.stderr.write(self.name + ": state = " + str(self.state) + ", Error: SACK timeout\n")
        self.send_sof_to_phy()

    def start_sack_timer(self):
        self.sack_timer = threading.Timer(self.sack_timeout, self.sack_timout_callback)
        self.sack_timer.start()

    def send_sof_to_phy(self):
        # Send sound if timout
        if self.sound_timout():
            self.send_sound_to_phy()
            return

        # Else, try to get a new MAC frame from transmission queue
        mpdu_payload, self.last_frame_n_blocks = self.create_mpdu_payload()
        if not mpdu_payload: 
            self.state = self.state_waiting_for_app
            if self.debug: print self.name + ": state = " + str(self.state) + ", no more data"
            return

        # If succeeded, send the SOF frame to Phy
        dict = gr.pmt.make_dict();
        dict = gr.pmt.dict_add(dict, gr.pmt.to_pmt("type"), gr.pmt.to_pmt("sof"))
        dict = gr.pmt.dict_add(dict, gr.pmt.to_pmt("modulation"), gr.pmt.from_uint64(self.modulation))
        dict = gr.pmt.dict_add(dict, gr.pmt.to_pmt("robo_mode"), gr.pmt.from_uint64(self.robo_mode))
        mpdu_payload_u8vector = gr.pmt.init_u8vector(len(mpdu_payload), list(mpdu_payload))
        if self.debug: print self.name + ": state = " + str(self.state) + ", sending MPDU (SOF, robo_mode=" + str(self.robo_mode) + ", modulation=" + str(self.modulation) + ") to PHY"
        self.state = self.state_sending_sof_sound
        self.message_port_pub(gr.pmt.to_pmt("phy out"), gr.pmt.cons(dict, mpdu_payload_u8vector))

    def send_sound_to_phy(self):
        if self.debug: print self.name + ": state = " + str(self.state) + ", sending MPDU (Sound) to PHY"
        self.state = self.state_sending_sof_sound
        dict = gr.pmt.make_dict();
        self.last_sound_frame = datetime.now();
        self.message_port_pub(gr.pmt.to_pmt("phy out"), gr.pmt.cons(gr.pmt.to_pmt("SOUND"), dict))

    def send_sack_to_phy(self):
        if self.debug: print self.name + ": state = " + str(self.state) + ", sending MPDU (SACK) to PHY"
        self.state = self.state_sending_sack
        sackd = bytearray(((len(self.last_frame_blocks_error) - 1) / 8) + 1 + 1)
        sackd[0] = 0b00010101
        for i in range(len(self.last_frame_blocks_error)):
            sackd[1 + i/8] = sackd[1 + i/8] | (self.last_frame_blocks_error[i] << (i % 8))
        sackd_u8vector = gr.pmt.init_u8vector(len(sackd), list(sackd))
        dict = gr.pmt.make_dict()
        dict = gr.pmt.dict_add(dict, gr.pmt.to_pmt("sackd"), sackd_u8vector)
        self.message_port_pub(gr.pmt.to_pmt("phy out"), gr.pmt.cons(gr.pmt.to_pmt("SACK"), dict))

    def send_idle_to_phy(self):
        dict = gr.pmt.make_dict()
        self.message_port_pub(gr.pmt.to_pmt("phy out"), gr.pmt.cons(gr.pmt.to_pmt("PHY-RXIDLE"), dict))

    def send_receive_to_phy(self):
        dict = gr.pmt.make_dict()
        self.message_port_pub(gr.pmt.to_pmt("phy out"), gr.pmt.cons(gr.pmt.to_pmt("PHY-SEARCHPPDU"), dict))

    def send_status_to_app(self):
        self.message_port_pub(gr.pmt.to_pmt("app out"), gr.pmt.to_pmt("READY"))

    def sound_timout(self):
        return (datetime.now() - self.last_sound_frame).total_seconds() >= self.sound_frame_rate

    def forecast(self, noutput_items, ninput_items_required):
        #setup size of input_items[i] for work call
        for i in range(len(ninput_items_required)):
            ninput_items_required[i] = noutput_items

    def start(self):
        self.send_status_to_app()

    def general_work(self, input_items, output_items):
        noutput_items = output_items[0].size
        ninput_items = input_items[0].size
        n = min(noutput_items, ninput_items)
        self.consume(0, len(input_items[0]))
        #self.consume_each(len(input_items[0]))
        return n

    def create_mac_frame(self, dest, payload, mgmt):
        if (not mgmt): 
            mft = 0b01 # MSDU payload
            mac_frame = bytearray(self.MAC_FRAME_OVERHEAD + len(payload)) # preallocate the frame
        else: 
            mft = 0b11 # management payload
            mac_frame = bytearray(self.MAC_FRAME_OVERHEAD + self.MAC_FRAME_CONFOUNDER_WIDTH + len(payload)) # preallocate the frame

        mfl = len(mac_frame) - self.MAC_FRAME_MFH_WIDTH - self.MAC_FRAME_ICV_WIDTH - 1 # calculate frame length field
        header = bytearray(2) # header is 2 bytes
        header[0] = (mfl & 0x3F) << 2 | mft  # concat frame legnth (14 bits) with frame type (2 bits)
        header[1] = (mfl & 0x3FC0) >> 6
        pos = self.set_bytes_field(mac_frame, header, self.MAC_FRAME_MFH_OFFSET, self.MAC_FRAME_MFH_WIDTH)
        if mgmt:  # only mgmt has confounder field
            pos = self.set_bytes_field(mac_frame, 0, pos, self.MAC_FRAME_CONFOUNDER_WIDTH)
        pos = self.set_bytes_field(mac_frame, dest, pos, self.MAC_FRAME_ODA_WIDTH)
        pos = self.set_bytes_field(mac_frame, self.device_addr, pos, self.MAC_FRAME_OSA_WIDTH)
        pos += self.MAC_FRAME_ETHERTYPE_OR_LENGTH_WIDTH
        pos = self.set_bytes_field(mac_frame, payload, pos, len(payload))        
        crc = self.crc32(mac_frame[self.MAC_FRAME_MFH_OFFSET + self.MAC_FRAME_MFH_WIDTH:-self.MAC_FRAME_ICV_WIDTH]) # calculate crc excluding MFH and ICV fields
        self.set_bytes_field(mac_frame, crc, pos, self.MAC_FRAME_ICV_WIDTH)

        return mac_frame

    def parse_mac_frame(self, mac_frame):
        pos = self.MAC_FRAME_MFH_OFFSET
        header = self.get_bytes_field(mac_frame, pos, self.MAC_FRAME_MFH_WIDTH)
        pos += self.MAC_FRAME_MFH_WIDTH
        mft = header[0] & 0x3
        length = (((header[0] & 0xFC) >> 2) | (header[1] << 6)) + self.MAC_FRAME_MFH_WIDTH + self.MAC_FRAME_ICV_WIDTH + 1
        if mft == 0b11: # determine frame type (management or data)
            confounder = self.get_bytes_field(mac_frame, pos, self.MAC_FRAME_CONFOUNDER_WIDTH)
            pos += self.MAC_FRAME_CONFOUNDER_WIDTH
            mgmt = True
        elif mft == 0b01:
            mgmt = False
        else:
            sys.stderr.write(self.name + ": state = " + str(self.state) + ", MAC frame type not supported\n")
            return

        dest_addr = self.get_bytes_field(mac_frame, pos, self.MAC_FRAME_ODA_WIDTH)
        pos += self.MAC_FRAME_ODA_WIDTH
        source_addr = self.get_bytes_field(mac_frame, pos, self.MAC_FRAME_OSA_WIDTH)
        pos += self.MAC_FRAME_OSA_WIDTH + self.MAC_FRAME_ETHERTYPE_OR_LENGTH_WIDTH
        payload = self.get_bytes_field(mac_frame, pos, length - pos - self.MAC_FRAME_ICV_WIDTH)
        if not self.crc32_check(mac_frame[self.MAC_FRAME_MFH_OFFSET + self.MAC_FRAME_MFH_WIDTH:]):
            sys.stderr.write(self.name + ": state = " + str(self.state) + ", MAC frame CRC error\n")
        return (payload, mgmt)

    def submit_mac_frame(self, frame, dest):
        if (str(dest) in self.tx_frames_buffer):
            stream = self.tx_frames_buffer[str(dest)]
        else:
            stream = {"ssn": 0, "frames": [], "remainder": bytearray(0)}
            self.tx_frames_buffer[str(dest)] = stream
        stream["frames"].append(frame)
        self.tx_frames_in_buffer += 1
        if self.tx_frames_in_buffer == self.MAX_FRAMES_IN_BUFFER: self.transmission_queue_is_full = True
        if self.debug: print self.name + ": state = " + str(self.state) + ", added MAC frame to tranmission queue, frame size = " + str(len(frame))

    def receive_mac_frame(self, frame):
        payload, mgmt = self.parse_mac_frame(frame)
        if payload:
            if not mgmt:
                if self.debug: print self.name + ": state = " + str(self.state) + ", received MAC frame, size = " + str(len(frame)) + ", sending payload to APP"
                pmt_dict = gr.pmt.make_dict();
                payload_u8vector = gr.pmt.init_u8vector(len(payload), list(payload))
                self.message_port_pub(gr.pmt.to_pmt("app out"), gr.pmt.cons(pmt_dict, payload_u8vector));
            else:
                if self.debug: print self.name + ": state = " + str(self.state) + ", received MAC frame (management), size = " + str(len(frame))
                self.process_mgmt_msg(payload)

    def init_phy_block(self, size, ssn, mac_boundary_offset, valid_flag, message_queue_flag, mac_boundary_flag, oldest_ssn_flag):
        phy_block = bytearray(size + 8)
        self.set_numeric_field(phy_block, ssn, self.PHY_BLOCK_HEADER_SSN_OFFSET, self.PHY_BLOCK_HEADER_SSN_WIDTH)
        if mac_boundary_flag == 1:
            self.set_numeric_field(phy_block, mac_boundary_offset, self.PHY_BLOCK_HEADER_MFBO_OFFSET, self.PHY_BLOCK_HEADER_MFBO_WIDTH)
        self.set_numeric_field(phy_block, valid_flag, self.PHY_BLOCK_HEADER_VPBF_OFFSET, self.PHY_BLOCK_HEADER_VPBF_WIDTH)
        self.set_numeric_field(phy_block, message_queue_flag, self.PHY_BLOCK_HEADER_MMQF_OFFSET, self.PHY_BLOCK_HEADER_MMQF_WIDTH)
        self.set_numeric_field(phy_block, mac_boundary_flag, self.PHY_BLOCK_HEADER_MMBF_OFFSET, self.PHY_BLOCK_HEADER_MMBF_WIDTH)
        self.set_numeric_field(phy_block, oldest_ssn_flag, self.PHY_BLOCK_HEADER_OPSF_OFFSET, self.PHY_BLOCK_HEADER_OPSF_WIDTH)
        return phy_block

    def create_mpdu_payload(self):
        # Check if buffer is empty
        if not len(self.tx_frames_buffer): 
            return ([], 0)
        stream = {}
        for key in self.tx_frames_buffer:
            if self.tx_frames_buffer[key]["frames"] or self.tx_frames_buffer[key]["remainder"]:
                stream = self.tx_frames_buffer[key]
                break
        if not stream: 
            return ([], 0)

        frames = stream["frames"]
        ssn = stream["ssn"]
        remainder = stream["remainder"]
        num_segments = 0
        payload = bytearray(0)
        end_of_stream = False

        while num_segments < self.MAX_SEGMENTS:
            # Creating a new segment
            mac_boundary_flag = False
            mac_boundary_offset = 0
            body_size = 512
            segment = remainder[0:body_size]
            if remainder:
                remainder = remainder[body_size:]
                if not remainder: self.tx_frames_in_buffer -= 1
            while len(segment) < body_size and frames:
                if not mac_boundary_flag:
                    mac_boundary_offset = len(segment)
                    mac_boundary_flag = True
                remainder = frames[0][body_size-len(segment):]
                segment += frames[0][0:body_size-len(segment)]                
                frames.pop(0)
                if not remainder: self.tx_frames_in_buffer -= 1

            # Determine if segment should be 128 bytes or 512
            if len(segment) < body_size:
                if len(segment) < 128 and num_segments == 0: body_size = 128 
                if not mac_boundary_flag:
                    mac_boundary_offset = len(segment)
                    mac_boundary_flag = True
                segment[len(segment):body_size] = bytearray(body_size-len(segment))
                
            # Creating the PHY block
            phy_block = self.init_phy_block(body_size, ssn, mac_boundary_offset, True, False, mac_boundary_flag, False) # Setting header fields
            pos = self.set_bytes_field(phy_block, segment, self.PHY_BLOCK_BODY_OFFSET, body_size) # assigning body
            crc = self.crc32(phy_block[0:-self.PHY_BLOCK_PBCS_WIDTH]) # calculate CRC
            self.set_bytes_field(phy_block, crc, pos, self.PHY_BLOCK_PBCS_WIDTH) # assinging CRC field
            num_segments += 1
            ssn = (ssn + 1) % 65636
            payload += phy_block

            # No more bytes, then break
            if not frames and not remainder:
                break
        stream["remainder"] = remainder
        stream["ssn"] = ssn

        if self.transmission_queue_is_full and self.tx_frames_in_buffer < self.MAX_FRAMES_IN_BUFFER:
            self.transmission_queue_is_full = False
            self.send_status_to_app()

        return (payload, num_segments)

    def parse_mpdu_payload(self, msdu_payload):
        phy_blocks_error = []
        phy_block_overhead_size = self.PHY_BLOCK_HEADER_WIDTH + self.PHY_BLOCK_PBCS_WIDTH
        if len(msdu_payload) > 128 + phy_block_overhead_size:
            phy_block_size = 512 + phy_block_overhead_size
        else:
            phy_block_size = 128 + phy_block_overhead_size
        j = 0
        while (j < len(msdu_payload)):
            phy_block = msdu_payload[j:j + phy_block_size]
            ssn = self.get_numeric_field(phy_block, self.PHY_BLOCK_HEADER_SSN_OFFSET, self.PHY_BLOCK_HEADER_SSN_WIDTH)
            if ssn != self.last_ssn+1:
                sys.stderr.write(self.name + ": state = " + str(self.state) + ", discontinued SSN numbering (last = " +str(self.last_ssn) + ", current = " + str(ssn) + "\n")
            self.last_ssn = ssn
            mac_boundary_offset = self.get_numeric_field(phy_block, self.PHY_BLOCK_HEADER_MFBO_OFFSET, self.PHY_BLOCK_HEADER_MFBO_WIDTH)
            mac_boundary_flag = self.get_numeric_field(phy_block, self.PHY_BLOCK_HEADER_MMBF_OFFSET, self.PHY_BLOCK_HEADER_MMBF_WIDTH)
            segment = self.get_bytes_field(phy_block, self.PHY_BLOCK_BODY_OFFSET, phy_block_size - phy_block_overhead_size)
            crc = self.get_bytes_field(phy_block, self.PHY_BLOCK_BODY_OFFSET + len(segment), self.PHY_BLOCK_PBCS_WIDTH)
            j += phy_block_size

            if not self.crc32_check(phy_block):
                sys.stderr.write(self.name + ": state = " + str(self.state) + ", PHY block CRC error\n")
                phy_blocks_error.append(1)
                continue
            else:
                phy_blocks_error.append(0)

            # Parsing segment
            i = 0
            if not mac_boundary_flag: mac_boundary_offset = len(segment) # if not mac boundary, use the whole segment
            mac_frame_data = segment[0:mac_boundary_offset]

            if mac_frame_data and ssn in self.rx_incomplete_frames:
                incomplete_frame = self.rx_incomplete_frames[ssn]
                incomplete_frame["data"] += mac_frame_data
                if incomplete_frame["length"] == 1: # length = 1 means the length is not calculated yet
                    header = incomplete_frame["data"][0:2]
                    incomplete_frame["length"] = (((header[0] & 0xFC) >> 2) | (header[1] << 6)) + self.MAC_FRAME_MFH_WIDTH + self.MAC_FRAME_ICV_WIDTH + 1                        
                if incomplete_frame["length"] == len(incomplete_frame["data"]):
                    self.receive_mac_frame(incomplete_frame["data"])
                else:
                    del self.rx_incomplete_frames[ssn]
                    next_ssn = (ssn + 1) % 65636
                    self.rx_incomplete_frames[next_ssn] = incomplete_frame

            i += len(mac_frame_data)
            while i < len(segment):
                length = 1
                if len(segment) - i >= self.MAC_FRAME_MFH_WIDTH:
                    header = segment[i:i + self.MAC_FRAME_MFH_WIDTH]
                    if header[0] & 0x03 == 0: # indicates zero padding segment
                        break
                    length = (((header[0] & 0xFC) >> 2) | (header[1] << 6)) + self.MAC_FRAME_MFH_WIDTH + self.MAC_FRAME_ICV_WIDTH + 1
                mac_frame_data = segment[i:i + length]
                if len(mac_frame_data) != length:
                    incomplete_frame = {}
                    incomplete_frame["data"] = mac_frame_data
                    incomplete_frame["length"] = length
                    next_ssn = (ssn + 1) % 65636
                    self.rx_incomplete_frames[next_ssn] = incomplete_frame
                else:
                    self.receive_mac_frame(mac_frame_data)
                i += len(mac_frame_data)

        return phy_blocks_error

    def parse_sackd(self, sackd):
        sacki = sackd[0]
        if not sacki == 0b00010101: 
            sys.stderr.write(self.name + ": state = " + str(self.state) + ", not supported sacki = " + str(sacki) + "\n")
        n_errors = 0
        for i in range(self.last_frame_n_blocks):
            n_errors += not (sackd[1 + i/8] & (1 << (i % 8)) == 0)
        return n_errors

    def create_mgmt_msg_cm_chan_est(self, bit_loading):
        mmentry = bytearray(self.MGMT_CM_CHAN_EST_NTMI_OFFSET + # preallocate the mmentry bytearray
                            self.MGMT_CM_CHAN_EST_NTMI_WIDTH + 
                            self.MGMT_CM_CHAN_EST_TMI_WIDTH + 
                            self.MGMT_CM_CHAN_EST_NINT_WIDTH + 
                            self.MGMT_CM_CHAN_EST_NEW_TMI_WIDTH + 
                            self.MGMT_CM_CHAN_EST_CPF_WIDTH + 
                            self.MGMT_CM_CHAN_EST_FECTYPE_WIDTH + 
                            self.MGMT_CM_CHAN_EST_GIL_WIDTH + 
                            self.MGMT_CM_CHAN_EST_CBD_ENC_WIDTH + 
                            self.MGMT_CM_CHAN_EST_CBD_LEN_WIDTH + 
                            self.MGMT_CM_CHAN_EST_CBD_WIDTH * len(bit_loading)) 
        pos = self.set_numeric_field(mmentry, 1, self.MGMT_CM_CHAN_EST_NTMI_OFFSET, self.MGMT_CM_CHAN_EST_NTMI_WIDTH)
        pos = self.set_numeric_field(mmentry, 1, pos, self.MGMT_CM_CHAN_EST_TMI_WIDTH)
        pos = self.set_numeric_field(mmentry, 0, pos, self.MGMT_CM_CHAN_EST_NINT_WIDTH)
        pos = self.set_numeric_field(mmentry, 1, pos, self.MGMT_CM_CHAN_EST_NEW_TMI_WIDTH)
        pos += self.MGMT_CM_CHAN_EST_CPF_WIDTH + self.MGMT_CM_CHAN_EST_FECTYPE_WIDTH + MGMT_CM_CHAN_EST_GIL_WIDTH
        pos = self.set_numeric_field(mmentry, 0, pos, self.MGMT_CM_CHAN_EST_CBD_ENC_WIDTH)
        pos = self.set_numeric_field(mmentry, len(bit_loading), pos, self.MGMT_CM_CHAN_EST_CBD_LEN_WIDTH)
        for i in range(n_carriers):
            pos = self.set_numeric_field(mmentry, bit_loading[i], pos, self.MGMT_CM_CHAN_EST_CBD_WIDTH)
        mgmt_msg = create_mgmt_msg(self.MGMT_MMTYPE_CM_CHAN_EST_ID, mmentry)
        mac_frame = create_mac_frame(dest, mgmt_message, True)
        return mac_frame

    def process_mgmt_msg_cm_chan_est(self, mmentry):
        new_tmi_offset = self.MGMT_CM_CHAN_EST_NTMI_OFFSET + \
                         self.MGMT_CM_CHAN_EST_NTMI_WIDTH + \
                         self.MGMT_CM_CHAN_EST_TMI_WIDTH + \
                         self.MGMT_CM_CHAN_EST_NINT_WIDTH
        new_tmi = self.get_numeric_field(mmentry, new_tmi_offset, self.MGMT_CM_CHAN_EST_NEW_TMI_WIDTH)
        cbd_len_offset = new_tmi_offset + \
                         self.MGMT_CM_CHAN_EST_NEW_TMI_WIDTH + \
                         self.MGMT_CM_CHAN_EST_CPF_WIDTH + \
                         self.MGMT_CM_CHAN_EST_FECTYPE_WIDTH + \
                         self.MGMT_CM_CHAN_EST_GIL_WIDTH + \
                         self.MGMT_CM_CHAN_EST_CBD_ENC_WIDTH
        cbd_len = self.get_numeric_field(mmentry, cbd_len_offset, self.MGMT_CM_CHAN_EST_CBD_LEN_WIDTH)
        bit_loading = [0] * cbd_len
        for i in range(cbd_len):
            bit_loading[i] = self.get_numeric_field(mmentry, cbd_offset, self.MGMT_CM_CHAN_EST_CBD_WIDTH)
            cbd_offset += self.MGMT_CM_CHAN_EST_CBD_WIDTH
        return bit_loading

    def create_mgmt_msg(self, mmtype, mmentry):
        self.set_numeric_field(mgmt_message, 0x1, self.MGMT_MMV_OFFSET, self.MGMT_MMV_WIDTH)
        self.set_numeric_field(mgmt_message, mmtype, self.MGMT_MMTYPE_OFFSET, self.MGMT_MMTYPE_WIDTH)
        self.set_bytes_field(mgmt_message, mmentry, self.MGMT_MMENTRY_OFFSET)

    def process_mgmt_msg(self, mgmt_msg):
        mmtype = self.get_numeric_field(mgmt_msg, self.MGMT_MMTYPE_OFFSET, self.MGMT_MMTYPE_WIDTH)
        mmentry = self.get_numeric_field(mgmt_msg, self.MGMT_MMENTRY_OFFSET, len(mgmt_msg) - self.MGMT_MMENTRY_OFFSET)
        if mmtype == self.MGMT_MMTYPE_CM_CHAN_EST_ID:
            self.process_mgmt_msg_cm_chan_est(mmentry)
        else: 
            sys.stderr.write (self.name + ": state = " + str(self.state) + ", management message (" + str(mmtype) + "not supported\n")

    def set_bytes_field(self, frame, bytes, offset, width):
        frame[offset:(offset + width)] = bytes
        return offset + width

    def get_bytes_field(self, frame, offset, width):
        return frame[offset:offset+width]

    def set_numeric_field(self, frame, value, offset, width = 1):
        shift = offset % 8
        shifted_length = ((shift + width - 1) / 8) + 1
        prev_byte = 0
        for i in range(shifted_length):
            byte = (value & (0xFF << i*8)) >> i*8
            frame[offset/8 + i] |= (byte << shift) & 0xFF | (prev_byte >> (8-shift))
            prev_byte = byte
        return offset+width

    def get_numeric_field(self, frame, offset, width = 1):
        value = 0
        shift = offset % 8
        shifted_length = ((shift + width - 1) / 8) + 1
        for i in range(shifted_length):
            value |= (frame[offset/8 + i] << i*8) >> shift
        value &= ((1 << width) - 1)
        return value

    def crc32(self, data):
        crc = binascii.crc32(data)
        return bytearray([crc & 0xFF, (crc >> 8) & 0xFF, (crc >> 16) & 0xFF, (crc >> 24) & 0xFF])

    def crc32_check(self, data):
        return (binascii.crc32(data) % 0xffffffff) == 0x2144df1c
