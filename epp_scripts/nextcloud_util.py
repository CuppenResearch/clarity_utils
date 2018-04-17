#import urllib2
from pprint import pprint
import re
import sys
import easywebdav
import os
import ntpath
import requests
import json
#import xml.dom.minidom
from xml.dom.minidom import parseString
from optparse import OptionParser
DEBUG = 0

class NextcloudUtil(object):

    def __init__( self ):
        if DEBUG > 0: print (self.__module__ + " init called")
        self.hostname = ""
        self.webdav = ""

    def setHostname( self, hostname ):
        if DEBUG > 0: print (self.__module__ + " setHostname called")
        self.hostname = hostname


    def setup( self, user, password ):

        if DEBUG > 0: print (self.__module__ + " setup called")
        self.user = user
        self.password = password
        self.webdav = easywebdav.connect(self.hostname , username=user, password=password, protocol='https')


    def upload(self, file_path):
        if not os.path.isfile(file_path): sys.exit("File path '{0}' is not a file".format(file_path))
        file_basename = ntpath.basename(file_path)
        remote_path = 'remote.php/webdav/sequencing_runs/'+file_basename

        if self.webdav.exists(remote_path):
            # sys.exit("File path '{0}' already exists on server".format(file_basename))
            # sys.exit("File path '{0}' already exists on server".format(file_basename))
            return {"ERROR" : "File path '{0}' already exists on server".format(file_basename)}
        else:
        #upload file
            self.webdav.upload(file_path, remote_path)

        #check if file upload succeeded
        upload_response = self.webdav.exists(remote_path)
        return {"SUCCES" : upload_response}

    def share(self, file_path, email):
        file_basename = ntpath.basename(file_path)
        remote_path = 'remote.php/webdav/sequencing_runs/'+file_basename

        if not self.webdav.exists(remote_path):
            return {"ERROR" : "File path '{0}' does not exist on server".format(file_basename)}

        # print "Share with {0}".format(email)
        data={
            'path' : "sequencing_runs/{0}".format(file_basename),
            'shareType' : 4,
            'shareWith' : 'useq@umcutrecht.nl'
        }



        response = requests.post("https://{0}/ocs/v1.php/apps/files_sharing/api/v1/shares".format(self.hostname), auth=(self.user, self.password), headers={'OCS-APIRequest':'true','Content-Type': 'application/json'},data=json.dumps(data))

        share_id = None
        if not self.webdav.exists(remote_path):
            return {"ERROR" : "File '{0}' upload failed".format(file_basename)}

        response_DOM = parseString( response.text )
        share_id = response_DOM.getElementsByTagName( "token" )[0].firstChild.data

        os.remove(file_path)
        return {"SUCCES": share_id}