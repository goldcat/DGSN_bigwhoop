#!/usr/bin/python

# thank you for those great libs!
from rtlsdr import RtlSdr
from rtlsdr import librtlsdr
import numpy as np
from xml.dom import minidom
import time
import pickle
import os
import json
from uuid import getnode as get_mac
import hashlib
import requests
import urllib2

from email import encoders
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate
import re
import smtplib
import zipfile

import platform

'''
BigWhoop...
will measure everything what is happening in the radio-frequency spectrum,
globally, continously, with your help!
'''

sw_version_counter = 1

'''
Global variables
'''
email_send = False
email_server = ""
email_user = ""
email_pass = ""
email_destination = ""


'''
starting the sdr-device and let it read out a number of samples
'''
def start_sdr(scan_frequency, scan_n_samples, sdr):
    # configure device
    # sdr.sample_rate = scan_samplerate  # Hz
    sdr.center_freq = scan_frequency     # Hz
    # sdr.freq_correction = 60   # PPM
    # sdr.gain = 'auto'
    # sdr.gain = 28
    sdr.gain = task_hw_setting_gain[0]
    result = sdr.read_samples(scan_n_samples)
    return result

'''
this is a a veeeeery simple spectrum analyzer hopping each
frequency to get the full spectrum that is possible with
"ezcap USB 2.0 DVB-T/DAB/FM dongle", more devices will follow
'''
def analyze_full_spectrum_basic(device_number, geo, loopcounter, loopstogo):
    print "you use a", librtlsdr.rtlsdr_get_device_name(device_number)

    scan_samplerate = task_hw_setting_samplerate[device_number]
    scan_n_samples = task_hw_setting_nsamples[device_number]

    # create object and start rtl-sdr device.
    # if more than one device, select it by device_number
    sdr = RtlSdr(device_index=device_number)

    # configure device
    sdr.sample_rate = scan_samplerate
    # sdr.freq_correction = 60   # PPM
    # sdr.gain = 'auto'
    # sdr.gain = 20

    result_timestamp = []
    result_geo_lon = []
    result_geo_lat = []
    result_geo_alt = []
    result_frequency = []
    result_mean_amplitude = []
    result_max_amplitude = []

    for scan_frequency in range(task_freq_scanstart[device_number], task_freq_scanend[device_number], scan_samplerate):
        result_timestamp.append(time.time())
        lon, lat, alt = geo.where()
        result_geo_lon.append(lon)
        result_geo_lat.append(lat)
        result_geo_alt.append(alt)

        sdr_iq_stream = start_sdr(scan_frequency, scan_n_samples, sdr)
        sdr_iq_stream = np.abs(sdr_iq_stream)
        mean = np.mean(sdr_iq_stream)
        max = np.max(sdr_iq_stream)
        progressbar = float(scan_frequency-task_freq_scanstart[device_number])/(task_freq_scanend[device_number]-task_freq_scanstart[device_number])
        progressbar = progressbar / float(loopstogo-1) + float(loopcounter) / float(loopstogo-1)
        print progressbar, scan_frequency, mean, max, lon, lat, alt

        result_frequency.append(scan_frequency)
        result_mean_amplitude.append(mean)
        result_max_amplitude.append(max)

        # creating the progress bar file used by BOINC.
        # 0.0 = 0%, 1.0 = 100% ready
        # only writing the last progress into the file
        # notice: this is only working for one scan. It does not include the scan duration yet!
        f = open('progressbar.csv', 'w+')
        f.write(str(progressbar))
        f.close()

    sdr.close()
    return [result_timestamp, result_frequency, result_mean_amplitude, result_max_amplitude, result_geo_lon, result_geo_lat, result_geo_alt]

'''
Get a unique filename to the given file.
'''
def get_unique_filename(filename):
    file_desc = get_node_id()[:8] + get_node_id()[-8:]\
            + "-" + (str(int(time.time()))\
            + "-" + os.path.basename(filename))
    return file_desc

'''
shortening just in case the input is too long. so people can include their
infos, but not too much
'''
def shortening_string(input):
    length = len(input)
    if length > 64:
        length = 64
    print input[:length]
    return input[:length]

'''
Loading in the ground station data.
Optionally, the user can put in data in there to provide additional information about his gs set up.
The only mandatory information is here to put in his geo location (long, lat, alt), but this will also be checked.
'''
def load_groundstation_config():
    doc = minidom.parse("set_your_groundstation_config.xml")

    global gs_meta, gs_sensor, gs_location
    gs_meta = []
    gs_sensor = []
    gs_location = []

    # doc.getElementsByTagName returns NodeList
    gs_meta.append(shortening_string(doc.getElementsByTagName("gs_name")[0].firstChild.data))
    gs_meta.append(shortening_string(doc.getElementsByTagName("gs_info")[0].firstChild.data))
    gs_meta.append(shortening_string(doc.getElementsByTagName("gs_info_url")[0].firstChild.data))

    gs_location.append(doc.getElementsByTagName("gs_location_long")[0].firstChild.data)
    gs_location.append(doc.getElementsByTagName("gs_location_lat")[0].firstChild.data)
    gs_location.append(doc.getElementsByTagName("gs_location_alt_meter")[0].firstChild.data)

    sensors = doc.getElementsByTagName("sensor")
    for sensor in sensors:
        gs_sensor.append(sensor.getAttribute("id"))
        gs_sensor.append(sensor.getElementsByTagName("sen_name")[0].firstChild.data)
        gs_sensor.append(sensor.getElementsByTagName("sen_usbport")[0].firstChild.data)
        gs_sensor.append(sensor.getElementsByTagName("sen_hw_ppm")[0].firstChild.data)
        gs_sensor.append(sensor.getElementsByTagName("sen_hw_modified")[0].firstChild.data)
        gs_sensor.append(sensor.getElementsByTagName("sen_hw_conversiondown")[0].firstChild.data)
        gs_sensor.append(sensor.getElementsByTagName("sen_hw_conversionup")[0].firstChild.data)
        gs_sensor.append(sensor.getElementsByTagName("sen_antenna")[0].firstChild.data)

'''
loading in the BOINC ready work unit data chunk.
this is currently xml, because it is human readable and the user will see, what is done
on the computer and scanned in the spectrum.
'''
def load_workunit():
    doc = minidom.parse("workunit.xml")

    global wuid
    global sid
    global task_durationmin
    global task_freq_scanstart
    global task_freq_scanend
    global task_analysis_mode
    global task_hw_setting_samplerate
    global task_hw_setting_gain
    global task_hw_setting_nsamples
    global email_send
    global email_server
    global email_user
    global email_pass
    global email_destination

    sid = []
    task_durationmin = []
    task_freq_scanstart = []
    task_freq_scanend = []
    task_analysis_mode = []
    task_hw_setting_samplerate = []
    task_hw_setting_gain = []
    task_hw_setting_nsamples = []

    # doc.getElementsByTagName returns NodeList
    wuid = doc.getElementsByTagName("wu_info")[0].firstChild.data
    print("Workunit Info:%s" %
           (wuid))

    tasks = doc.getElementsByTagName("task")
    email_data = doc.getElementsByTagName("email")

    for task in tasks:
        sid.append(int(task.getAttribute("id")))
        task_durationmin.append(int(task.getElementsByTagName("task_durationmin")[0].firstChild.data))
        task_freq_scanstart.append(int(task.getElementsByTagName("task_freq_scanstart")[0].firstChild.data))
        task_freq_scanend.append(int(task.getElementsByTagName("task_freq_scanend")[0].firstChild.data))
        task_analysis_mode = task.getElementsByTagName("task_analysis_mode")[0]
        task_hw_setting_samplerate.append(int(task.getElementsByTagName("task_hw_setting_samplerate")[0].firstChild.data))
        task_hw_setting_gain.append(int(task.getElementsByTagName("task_hw_setting_gain")[0].firstChild.data))
        task_hw_setting_nsamples.append(int(task.getElementsByTagName("task_hw_setting_nsamples")[0].firstChild.data))

    try:
        for email in email_data:
            if email.getAttribute("send") in\
                ['TRUE', 'True', 'true', '1', 'y', 'yes', 'on']:
                email_send = True
                print "[>] email containing results will be sent"
                email_server = str(email\
                    .getElementsByTagName("email_server")[0]\
                    .firstChild.data)
                email_user = str(email\
                    .getElementsByTagName("email_user")[0]\
                    .firstChild.data)
                email_pass = str(email\
                    .getElementsByTagName("email_pass")[0]\
                    .firstChild.data)
                email_destination = str(email\
                    .getElementsByTagName("email_destination")[0]\
                    .firstChild.data)
    except AttributeError:
        print "[>] no email option provided: "\
              "sending results via email not possible"

'''
In case of a hard shut off/down of the computer and software, the software will dump and resume from a
savepoint file that is performed here.
It is a simple python pickle.
'''
def boinc_dump_savepoint_file(filename, result, timer, loopcounter):
    pickle.dump( [timer, result, loopcounter], open( filename, "wb" ) )

def boinc_load_savepoint_file(filename):
    input = pickle.load( open( filename, "rb" ) )
    return input[0], input[1], input[2]

'''
Clean all results
'''
def clean_results():
    print('> cleaning previous results ...'),
    pattern = ".*-.*-result.json"
    for f in os.listdir('.'):
        if re.search(pattern, f):
            os.remove(os.path.join('.', f))
    print "done"

'''
Cleanup temporary files witch were used for preparing the outgoing e-mail.
'''
def cleanup_dir(output_files_zip):
    print('> cleaning temporary files ...'),
    for f in output_files_zip:
        os.remove(f)
    print "done"


'''
writing the output of the analysis.
it is js for now and will be specified in the next team meeting
'''
def writing_output(container):
    clean_results()
    output_files = []
    output_files.append(get_unique_filename("result.json"))
    getout = (json.dumps(container, sort_keys=True, indent=4))
    f = open(output_files[0], "w+")
    f.write(getout)
    f.close
    return output_files

'''
creating a dictionary for all the output data
'''
def create_out_structure():
    meta = {}
    meta['client'] = {}
    meta['client']['id'] = 'hash value'
    meta['client']['name'] = 'NodeZero'
    meta['client']['url'] = 'www.AerospaceResearch.net'

    meta['client']['sensor'] = {}
    meta['client']['sensor']['id'] = 0
    meta['client']['sensor']['name'] = 'generic sdr device'
    meta['client']['sensor']['devicename'] = 'generic sdr device entered by user'
    meta['client']['sensor']['usbport'] = 'generic sdr device'
    meta['client']['sensor']['ppm'] = 0
    meta['client']['sensor']['modified'] = 0
    meta['client']['sensor']['conversiondown'] = 0
    meta['client']['sensor']['conversionup'] = 0
    meta['client']['sensor']['antenna'] = 'custom,dipol,75cm'

    meta['sw'] = {}
    meta['sw']['version'] = 0
    meta['sw']['os'] = 'WinLinuxOS'
    meta['sw']['bit'] = '32bit64bit'

    data = {}
    data['workunitid'] = {}
    data['dataset'] = {}

    return {'meta' : meta, 'data' : data}

'''
here, the json putput is stored in a json table for the data-set field.
this is still specific and needs to be changed for other functions!
the style is based on this for now http://www.patrick-wied.at/static/heatmapjs/example-heatmap-googlemaps.html
'''
def creating_json_data(input):
    out = []
    for k in range(len(input)):
        for l in range(len(input[k][0])):
            out.append({'timestamp' : input[k][0][l], 'frequency' : input[k][1][l], 'mean_amplitude' : input[k][2][l], 'max_amplitude' : input[k][3][l], 'lon' : input[k][4][l], 'lat' : input[k][5][l], 'alt' : input[k][6][l]})
    return out

'''
get a unique node id, but a bit disguised
'''
def get_node_id():
    node_id = hashlib.sha224(str(get_mac()))
    node_id = node_id.hexdigest()
    return node_id

'''
checking, if the internet is on.
this is used for the geo location cross check, where the node is roughly located
'''
def internet_on(url):
    try:
        response=urllib2.urlopen(url,timeout=1)
        return True
    except urllib2.URLError as err: pass
    return False

'''
finding this node's position.
also a cross check between where the user puts in the node's position,
and where other sources states, where it COULD be.
let's make sure, this won't tell us too much about the user!
'''
class geo_location():
    def __init__(self):
        # This example requires the Requests library be installed.
        # You can learn more about the Requests library here:
        # http://docs.python-requests.org/en/latest/

        # standard geo references taken by the user inputs
        self.ip = '127.0.0.1'
        self.lon = 0.0
        self.lat = 0.0
        self.alt = 0.0

        # checking input syntax to find floats and strings with EW and NS. Perhaps more fallbacks needed.
        if gs_location[0].find("E") > -1:
            self.lon = float(gs_location[0][0:gs_location[0].find("E")-1])
        elif gs_location[0].find("W") > -1:
            self.lon = -1.0*float(gs_location[0][0:gs_location[0].find("W")])
        else:
            self.lon = float(gs_location[0])

        self.lat = gs_location[1]

        if gs_location[1].find("N") > -1:
            self.lat = float(gs_location[1][0:gs_location[1].find("N")-1])
        elif gs_location[1].find("S") > -1:
            self.lat = -1.0*float(gs_location[1][0:gs_location[1].find("S")])
        else:
            self.lat = float(gs_location[1])

        self.alt = float(gs_location[2])


        self.ip_lon = 0.0
        self.ip_lat = 0.0
        self.ip_alt = 0.0

        '''
        just checking, if there is an accessible internet connection
        '''
        url_ip = 'http://api.ipify.org'
        internetison = internet_on(url_ip)

        if internetison:
            self.ip = requests.get(url_ip).text
            print 'My public IP address is:', self.ip

            send_url = 'http://freegeoip.net/json'
            r = requests.get(send_url)
            j = json.loads(r.text)
            self.ip_lon = float(j['longitude'])
            self.ip_lat = float(j['latitude'])

            # first check if user input of geo is in range of ip determined geo location
            # another inout for a quorum of 3 would be needed! But for now, it's better than nothing o have this check.
            # also keeping in mind users behind a proxy or anonymizer having another ip of somehwere else.
            if abs(self.ip_lon - self.lon) > 5.0 or abs(self.ip_lat - self.lat) > 5.0:
                print "using the geo position found based on the ip-address"
                self.lon = self.ip_lon
                self.lat = self.ip_lat

    def where(self):
        return self.lon, self.lat, self.alt


'''
Compress given files in 'result.zip'.
'''
def zip_files(output_files):
    output_zip = get_unique_filename('result.zip')
    print("> zipping output files ..."),
    try:
        zf = zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED)
        for output_file in output_files:
            zf.write(output_file)
    finally:
        zf.close()
    print "done"
    return output_zip

'''
Send resulting data via e-mail.
'''
def send_results_email(results):
    if email_send and\
       email_server and\
       email_user and\
       email_pass and\
       email_destination:

        output_files_zip = []
        output_files_zip.append(zip_files(results))
        print("> sending email ..."),
        subject = "DGSN BigWhoop Data"
        sender = email_user
        receivers = []
        receivers.append(email_destination)
        text = "This e-mail contains collected data from the\n"\
               "Distributed Ground Station Network (DGSN).\n"
        email = MIMEMultipart()
        email['Subject'] = subject
        email['To'] = COMMASPACE.join(receivers)
        email.attach(MIMEText(text, 'plain'))
        for f in output_files_zip or []:
            with open(f, "rb") as fl:
                # Send the results with an unique label containing
                # the first and the last few chars from the user id
                # and append the current unix timestamp.
                file_desc = get_unique_filename("result.zip");
                part=MIMEBase('application','zip')
                part.set_payload(fl.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', 'attachment',\
                            filename=file_desc,\
                            desc=file_desc)
                email.attach(part)
        try:
            smtpsrv = smtplib.SMTP(email_server, 587)
            smtpsrv.ehlo()
            smtpsrv.starttls()
            smtpsrv.ehlo
            smtpsrv.login(email_user, email_pass);
            smtpsrv.sendmail(sender, receivers, email.as_string())
            smtpsrv.close()
            print "done and done"
        except smtplib.SMTPHeloError:
            print "Error: unable to send email (wrong reply from server)"
        except smtplib.SMTPAuthenticationError:
            print "Error: unable to send email (login failed)"
        except smtplib.SMTPException:
            print "Error: unable to send email (auth method failed)"
        except smtplib.SMTPException:
            print "Error: unable to send email"
        cleanup_dir(output_files_zip)

'''
let's start here.
'''
def main():
    print "loading groundstation config data..."
    load_groundstation_config()
    print gs_meta
    print gs_location

    print "loading the workunit data"
    load_workunit()

    filename_savepoint = "savepoint.p"
    if os.path.exists(filename_savepoint):
        print "loading savepoints"

    result = []

    print "scanning spectrum is in between", task_freq_scanstart, "and", task_freq_scanend
    if librtlsdr.rtlsdr_get_device_count() > 0:
        print "starting sdr-device..."
        print "for now, only one device is used. Soon, more..."
        device_number = 0

        # getting the rough location of this node
        geo = geo_location()

        # setting the scan timer
        # and loading the saved data to start from there
        if os.path.exists(filename_savepoint):
            time_counter, result, loopcounter = boinc_load_savepoint_file(filename_savepoint)
            print time_counter
            print result
        else:
            time_counter = 0.0
            loopcounter = 0

        # preparation of the output structure as json for everything meta and data
        container = create_out_structure()


        # estimating total while iterations
        loopstogo = (task_freq_scanend[device_number] - task_freq_scanstart[device_number])
        loopstogo = loopstogo * task_hw_setting_nsamples[device_number] / (task_hw_setting_samplerate[device_number]**2)
        loopstogo = int(np.round(float(task_durationmin[device_number]) / float(loopstogo)))

        # start the scanning cycle with time and frequencies.
        # currently, only time base can be resumed.
        # import matplotlib.pyplot as plt
        while time_counter < task_durationmin[device_number]:
            time_start = time.time()

            result.append(analyze_full_spectrum_basic(device_number, geo, loopcounter, loopstogo))

            time_counter = time_counter + (time.time() - time_start)
            loopcounter += 1

            boinc_dump_savepoint_file(filename_savepoint, result, time_counter, loopcounter)

            # plt.plot(result[-1][1],result[-1][2])
            # plt.plot(result[-1][1],result[-1][3])
            print "time to go",time_counter, " result", result
        # plt.ylabel('some numbers')
        # plt.show()


        #wrapping and cleaning up
        container['meta']['client']['id'] = get_node_id()
        container['meta']['client']['name'] = gs_meta[0]
        container['meta']['client']['info'] = gs_meta[1]
        container['meta']['client']['url'] = gs_meta[2]
        container['meta']['client']['sensor']['id'] = int(gs_sensor[0])
        container['meta']['client']['sensor']['name'] = gs_sensor[1]
        container['meta']['client']['sensor']['devicename'] = librtlsdr.rtlsdr_get_device_name(device_number)
        container['meta']['client']['sensor']['usbport'] = gs_sensor[2]
        container['meta']['client']['sensor']['ppm'] = int(gs_sensor[3])
        container['meta']['client']['sensor']['modified'] = gs_sensor[4]
        container['meta']['client']['sensor']['conversiondown'] = gs_sensor[5]
        container['meta']['client']['sensor']['conversionup'] = gs_sensor[6]
        container['meta']['client']['sensor']['antenna'] = gs_sensor[7]

        container['meta']['sw']['version'] = sw_version_counter
        container['meta']['sw']['os'] = platform.platform()

        container['data']['workunitid'] = wuid
        container['data']['dataset'] = {}
        container['data']['dataset']['analyze_full_spectrum_basic'] = creating_json_data(result)
        container['data']['dataset']['analyze_adsb'] = [{'timestamp' : 1111111, 'lon' : 111, 'lat' : 88, 'alt' : 9999}]

        output_files = writing_output(container)
        send_results_email(output_files)
        os.remove(filename_savepoint)

    else:
        print "no sdr-device found"

    print "thank you for helping"

'''
    Entry point.
'''
if __name__ == '__main__':
    main()
