import glsapiutil
import xml.dom.minidom
import smtplib
import codecs
import json
import urllib2
import os
import tarfile
import sys
import multiprocessing
import subprocess
from xml.dom.minidom import parseString, parse
from optparse import OptionParser
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from xml.parsers.expat import ExpatError
from nextcloud_util import NextcloudUtil
import xml.etree.cElementTree as ET
import datetime
import getpass

HOSTNAME = ''
VERSION = ''
BASE_URI = ''

DEBUG = True
api = None
options = None
CACHE = {}
RUN_TYPES = ['NextSeq Run (NextSeq) 1.0','USEQ - NextSeq Run', 'MiSeq Run (MiSeq) 4.0', 'USEQ - MiSeq Run','HiSeq Run (HiSeq) 5.0','USEQ - HiSeq Run']
RUNTYPE_YIELDS={
    "Version3" : 20000000, #MiSeq
    "Version2" : 12000000, #MiSeq
    "NextSeq Mid" : 120000000, #NextSeq
    "NextSeq High" : 350000000, #NextSeq
    "HiSeq rapid" : 250000000, #Hiseq
}





def getObjectDOM( uri ):

    global CACHE
    #global api
    if uri not in CACHE.keys():
        #print uri
        thisXML = api.getResourceByURI( uri )
        # print thisXML
        thisDOM = parseString( thisXML )
        CACHE[ uri ] = thisDOM

    return CACHE[ uri ]


def setupGlobalsFromURI( uri ):

	global HOSTNAME
	global VERSION
	global BASE_URI

	tokens = uri.split( "/" )
	HOSTNAME = "/".join(tokens[0:3])
	VERSION = tokens[4]
	BASE_URI = "/".join(tokens[0:5]) + "/"

	if DEBUG is True:
		print HOSTNAME
		print BASE_URI

def getArtifacts( ids ):
	artifactLinksXML = []

	artifactLinksXML.append( '<ri:links xmlns:ri="http://genologics.com/ri">' )
	for limsid in ids:
		artifactLinksXML.append( '<link uri="' + BASE_URI + 'artifacts/' + limsid + '" rel="artifacts"/>' )

	artifactLinksXML.append( '</ri:links>' )
	artifactLinksXML = ''.join( artifactLinksXML )

	artifactsXML = api.getBatchResourceByURI( BASE_URI + "artifacts/batch/retrieve", artifactLinksXML )
	## did we get back anything useful?
	try:
		artifactsDOM = parseString( artifactsXML )
		nodes = artifactsDOM.getElementsByTagName( "art:artifact" )
		if len(nodes) > 0:
			response = nodes
		else:
			response = ""
	except:
		response = ""

	return response

def getSamples( ids ):

	sampleLinksXML = []
	sampleLinksXML.append( '<ri:links xmlns:ri="http://genologics.com/ri">' )

	for limsid in ids:
		sampleLinksXML.append( '<link uri="' + BASE_URI + 'samples/' + limsid + '" rel="sample"/>' )

	sampleLinksXML.append( '</ri:links>' )
	sampleLinksXML = ''.join( sampleLinksXML )
	samplesXML = api.getBatchResourceByURI( BASE_URI + "samples/batch/retrieve", sampleLinksXML )

	## did we get back anything useful?
	try:
		samplesDOM = parseString( samplesXML )
		nodes = samplesDOM.getElementsByTagName( "smp:sample" )
		if len(nodes) > 0:
			response = nodes
		else:
			response = ""
	except:
		response = ""

	return response

def getRunInfo( project_name ):

    processes_DOM = getObjectDOM("{0}processes/?projectname={1}&type={2}".format(BASE_URI, project_name, "&type=".join([urllib2.quote(x) for x in RUN_TYPES])))
    
    process_nodes = processes_DOM.getElementsByTagName("process")
    print project_name
    runs = {}
    for process in process_nodes:
        #print process.getAttribute("uri")
        process_DOM = getObjectDOM( process.getAttribute("uri") )
        run_date = process_DOM.getElementsByTagName("date-run")[0].firstChild.data
        run_id = api.getUDF(process_DOM, "Run ID")
        run_flowcell = api.getUDF(process_DOM, "Flow Cell ID")
        
        runs[run_date] = [run_id, run_flowcell]
	print 'id',run_id

    run_dates = [datetime.datetime.strptime(ts, "%Y-%m-%d") for ts in runs.keys()]
    run_dates.sort()
    sorted_run_dates = [datetime.datetime.strftime(ts, "%Y-%m-%d") for ts in run_dates]
    return runs[sorted_run_dates[-1]] #return the most recent run, this is the run we want to share

def parseRunParameters(run_parameters):
    run_parameters = parse(run_parameters)
    expected_reads = '0'
    try:
        run_chem = run_parameters.getElementsByTagName('Chemistry')[0].firstChild.nodeValue
    except:
        run_chem = ''
    try:
        run_version = run_parameters.getElementsByTagName('ReagentKitVersion')[0].firstChild.nodeValue
    except:
        run_version = ''
    if run_chem in RUNTYPE_YIELDS:
        expected_reads = RUNTYPE_YIELDS[run_chem]
    elif run_version in RUNTYPE_YIELDS:
        expected_reads = RUNTYPE_YIELDS[run_version]
    else:
        expected_reads = RUNTYPE_YIELDS['HiSeq rapid']

    return expected_reads

def parseConversionStats( conversion_stats) :
    tree = ET.ElementTree(file=conversion_stats)
    stats_summary = {'samples':{}, 'unknown':{}, 'total_reads' : 0, 'total_reads_raw' : 0}

    paired_end = False
    for elem in tree.iter(tag='Sample'):

        sample_name = elem.attrib['name']

        if sample_name != "all":
            barcode = elem.find('Barcode')
            barcode_name = barcode.attrib['name']
            if "N" in barcode_name:
                continue


            stats_summary['samples'][ sample_name ] = {}
            stats_summary['samples'][ sample_name] = {'barcode':barcode_name, 'qsum':0,'yield':0,'yield_Q30':0,'cluster_count':0, 'mean_quality':0, 'percent_Q30':0}
            for lane in barcode.findall("Lane"):
                lane_nr = lane.attrib["number"]
                lane_counts = {
                    'pf' : {'r1':{'yield':0,'yield_Q30':0,'qscore_sum':0}, 'r2':{'yield':0,'yield_Q30':0,'qscore_sum':0}}
                }
                for tile in lane.findall("Tile"):

                    tile_nr = tile.attrib["number"]
                    raw_counts = tile.find("Raw")
                    pf_counts = tile.find("Pf")

                    stats_summary['samples'][ sample_name]['cluster_count'] += int(pf_counts.find("ClusterCount").text)
                    stats_summary['total_reads'] += int(pf_counts.find("ClusterCount").text)
                    stats_summary['total_reads_raw'] += int(raw_counts.find("ClusterCount").text)

                    for read in pf_counts.findall("Read"):
                        read_number = read.attrib["number"]
                        lane_counts['pf']['r'+str(read_number)]['yield'] += int(read.find("Yield").text)
                        lane_counts['pf']['r'+str(read_number)]['yield_Q30'] += int(read.find("YieldQ30").text)
                        lane_counts['pf']['r'+str(read_number)]['qscore_sum'] += int(read.find("QualityScoreSum").text)

                    stats_summary['samples'][ sample_name]['qsum'] += lane_counts['pf']['r1']['qscore_sum']
                    stats_summary['samples'][ sample_name]['qsum'] += lane_counts['pf']['r2']['qscore_sum']
                    stats_summary['samples'][ sample_name]['yield'] += lane_counts['pf']['r1']['yield']
                    stats_summary['samples'][ sample_name]['yield'] += lane_counts['pf']['r2']['yield']
                    stats_summary['samples'][ sample_name]['yield_Q30'] += lane_counts['pf']['r1']['yield_Q30']
                    stats_summary['samples'][ sample_name]['yield_Q30'] += lane_counts['pf']['r2']['yield_Q30']

            stats_summary['samples'][ sample_name ]['percent_Q30'] = "{0:.2f}".format( (stats_summary['samples'][ sample_name ]['yield_Q30'] / float(stats_summary['samples'][ sample_name ]['yield']))*100 )
            stats_summary['samples'][ sample_name ]['mean_quality'] = "{0:.2f}".format( stats_summary['samples'][ sample_name ]['qsum'] / float(stats_summary['samples'][ sample_name ]['yield']) )
            stats_summary['samples'][ sample_name ]['cluster_count'] = "{0:,}".format( stats_summary['samples'][ sample_name]['cluster_count'] )

    for top_unknown in tree.findall("TopUnknownBarcodes"):
        for barcode in top_unknown.findall("Barcode"):
            bc_count = int(barcode.attrib["count"])
            bc_seq = barcode.attrib["sequence"]
            if bc_seq in stats_summary['unknown']:
                stats_summary['unknown'][bc_seq] += bc_count
            else:
                stats_summary['unknown'][bc_seq] = bc_count

    for bc in stats_summary['unknown']:
        stats_summary['unknown'][bc] = "{0:,}".format(stats_summary['unknown'][bc])

    return stats_summary


def getRunDirectory( run_name=None, run_flowcell=None ):
    run_dir = None
    if run_name:
        for item in os.listdir(options.dataDir):
        #print os.path.join( options.dataDir, item, run_name )
            if os.path.isdir( os.path.join( options.dataDir, item, run_name ) ):
                run_dir = os.path.join( options.dataDir, item, run_name )
    elif run_flowcell:
        res=[]
        for root,dirs,files in os.walk(options.dataDir, topdown=True):
            for d in dirs:
                path = os.path.join(root,d)
                
                #if path.count("/") == 7:
                if path.endswith("_000000000-"+run_flowcell):
                    run_dir = path
                    break
    return run_dir

def zipRun( project_id, run_dir ):
    
    run_name = os.path.basename(run_dir)
    run_zip = "{0}/{1}.tar.gz".format(run_dir,project_id)
    
    with tarfile.open(run_zip, "w:gz") as tar:
        tar.add(run_dir, arcname=run_name)
    
    return run_zip

def encryptRun( run_zip, researcher_email, researcher_user_name):

    return_code = subprocess.call("gpg --encrypt --output {0}.gpg --recipient '{1}' {0}".format(run_zip,researcher_email), shell=True)
    if return_code:
        sys.exit("Encryption failed with message : {0}".format(return_code))
    else:
        os.remove(run_zip)


    return run_zip+".gpg"


def getResearcher( uri ):
    r_DOM = getObjectDOM( uri )
    email = r_DOM.getElementsByTagName( "email" )[0].firstChild.data
    user_name = r_DOM.getElementsByTagName( "username" )[0].firstChild.data

    if not email or not user_name:
        sys.exit("Could not find researcher uri {}".format(uri))

    return {'email':email,'user_name':user_name}

def sendMail(project_id, researcher_email, share_id, conversion_stats, expected_reads):

    outer = MIMEMultipart()
    outer[ "Subject" ] = "USEQ sequencing of sequencing-run ID {0} finished".format(project_id)
    outer[ "From" ] = 'useq@umcutrecht.nl'

    contents = ""
    contents += "<p>Dear USEQ user,</p>"
    contents += "<p>Sequencing-run ID {0} has succesfully been sequenced. You can find a short run report below.</p>".format(project_id)
    contents += "<p>You can download your data using <a href='https://ncie01.op.umcutrecht.nl/index.php/s/{0}'>this</a> link.</p>".format(share_id)
    contents += "<p>This link will remain active for 7 days. If you're unable to download your data within this period, please let us know. "
    contents += "Please also be aware that we're able to store your sequencing data for a maximum of two months, after which it is automatically deleted from our servers.</p>"
    contents += "<h3>Summary</h3>"
    contents += \
    "<table>\
        <tr><td><b>Expected Raw Reads:</b></td><td>{0}</td></tr>\
        <tr><td><b>Raw Reads:</b></td><td>{1}</td></tr>\
        <tr><td><b>Filtered Reads:</b></td><td>{2}</td></tr>\
    </table>".format(expected_reads,conversion_stats['total_reads_raw'],conversion_stats['total_reads'])
    contents += "<h3>Details</h3>"
    contents += \
    "<table border='1'>\
        <tr>\
            <th><b>Sample</b></th>\
            <th><b>Barcode Sequence</b></th>\
            <th><b>Reads</b></th>\
            <th><b>% >= Q30</b></th>\
            <th><b>Mean Quality Score</b></th>\
        </tr>"
    for sample in conversion_stats['samples']:
        barcode = conversion_stats['samples'][sample]['barcode']
        cluster_count = conversion_stats['samples'][sample]['cluster_count']
        percent_Q30 = conversion_stats['samples'][sample]['percent_Q30']
        mean_quality = conversion_stats['samples'][sample]['mean_quality']
        contents += \
        "<tr>\
            <td>{0}</td>\
            <td>{1}</td>\
            <td>{2}</td>\
            <td>{3}</td>\
            <td>{4}</td>\
        </tr>".format(sample, barcode, cluster_count, percent_Q30, mean_quality)

    contents += "</table>"
    logo = '../resources/useq_logo.jpg'
    logo_name = 'useq_logo.jpg'

    contents += "<p>Kind regards,</p>"
    contents += "<p>The USEQ team</p><img src='cid:logo_image' style='width:30%;height:30%;'><p>"
    contents += "<i>Utrecht Sequencing Facility (USEQ) | Joint initiative of the University Medical Center Utrecht, "
    contents += "Hubrecht Institute and Utrecht University Center for Molecular Medicine | UMC Utrecht | room STR2.207 | "
    contents += "Heidelberglaan 100 | 3584 CX Utrecht | The Netherlands | Tel: +31 (0)88 75 55164 | "
    contents += "<a href='mailto:USEQ@umcutrecht.nl'>USEQ@umcutrecht.nl</a> | <a href='www.USEQ.nl'>www.USEQ.nl</a></i></p>"
    #print contents

    contents = MIMEText( contents, 'html')
    outer.attach( contents )

    #read the logo and add it to the email
    fp = open(logo, 'rb')
    logo_image = MIMEImage(fp.read())
    fp.close()
    logo_image.add_header('Content-ID', '<logo_image>')
    outer.attach(logo_image)

    s = smtplib.SMTP( "localhost" )
    recipients = [researcher_email, 'useq@umcutrecht.nl']
    #recipients = ['s.w.boymans@gmail.com', 'useq@umcutrecht.nl']
    s.sendmail( 'useq@umcutrecht.nl', recipients, outer.as_string() )

    s.quit()

def shareWorker(project_name, project_id, researcher_email, researcher_user_name):
    name = multiprocessing.current_process().name
    print "{0} : Starting".format(name)

    run_info = getRunInfo(project_name)
    run_name = run_info[0]
    run_flowcell = run_info[1]
    print run_info
    if run_name:
        run_dir = getRunDirectory( run_name = run_name )
    elif run_flowcell:
        run_dir = getRunDirectory( run_flowcell = run_flowcell )
    else:
        print "{0} : No run name found for {1}".format(name,project_name)
        return
    
    #print run_dir
    if not run_dir:
         print "{0} : Could not find {1} in {2}".format(name, run_dir, options.dataDir)
         return

    conversion_stats = parseConversionStats('{}/Data/Intensities/BaseCalls/Stats/ConversionStats.xml'.format(run_dir))
    expected_reads = parseRunParameters('{}/RunParameters.xml'.format(run_dir))

    run_zip = zipRun( project_id,run_dir )

    if options.shareonly != 'yes':
        if options.encrypt == 'yes':
            print "{0} : Running encryption of {1}".format(name, run_zip)
            run_zip = encryptRun( run_zip, researcher_email,researcher_user_name )

        upload_response = nc_util.upload(run_zip)
        if "ERROR" in upload_response:
            print "{0} : Uploading of {1} failed with message:\n '{2}'".format(name, run_zip, upload_response["ERROR"])
            return

    share_response = nc_util.share(run_zip, researcher_email)
    if "ERROR" in share_response:
        print "{0} : Sharing of {1} failed with message:\n '{2}'".format(name, run_zip, share_response["ERROR"])
        return
    else:
        share_id = share_response["SUCCES"]
        print "{0} : Sending {1} to {2} with id {3}".format(name,run_zip,researcher_email,share_id)
        sendMail(project_id, researcher_email, share_id, conversion_stats, expected_reads)
        print "{0} : Finished".format(name)
        return


def shareFromProjectId():

    project_ids = options.projectids.split(",")
    share_workers = []
    for project_id in project_ids:

        p_XML = api.getResourceByURI( BASE_URI + 'projects/' + project_id)
        p_DOM = parseString( p_XML )

        project_name = p_DOM.getElementsByTagName( "name" )[0].firstChild.data
        researcher_uri = p_DOM.getElementsByTagName( "researcher" )[0].getAttribute( "uri" )
	#print "Project name",project_name
	
        researcher = getResearcher( researcher_uri )
        researcher_email = researcher['email']
        researcher_user_name = researcher['user_name']
	#print "Researcher",researcher

        run_info = getRunInfo(project_name)
        run_name = run_info[0]
        run_flowcell = run_info[1]

	#print "Run info",run_info
        share_worker = multiprocessing.Process(name="Worker_{0}".format(project_name), target=shareWorker, args=(project_name,project_id, researcher_email,researcher_user_name))

        share_workers.append( share_worker)
        share_worker.start()

    for w in share_workers:
        w.join()




def shareFromStep():


    stepURI = options.stepURI + "/details"
    stepDOM = getObjectDOM( stepURI )
    #Check if nextseq pool, else don't copy samplesheet

    sequencing_runs = {}
    #Get the input analytes lims ids
    analyteIDS = []
    for input in stepDOM.getElementsByTagName( "input" ):
        analyteID = input.getAttribute( "limsid" )


        if analyteID not in analyteIDS:
            analyteIDS.append( analyteID )

    #Get the input artifacts (which is a pool of samples) by lims id
    # print "AnalyteIDs","\t".join(analyteIDS)

    share_workers = []
    artifacts = getArtifacts( analyteIDS )
    for artifact in artifacts:
        pool_uri = artifact.getAttribute( "uri")
        pool_id = artifact.getAttribute( "limsid" )
        pool_name = artifact.getElementsByTagName("name")[0].firstChild.data
        first_sample_id = artifact.getElementsByTagName("sample")[0].getAttribute("limsid")
        first_sample_DOM = getSamples([first_sample_id])[0]
        project_id = first_sample_DOM.getElementsByTagName("project")[0].getAttribute("limsid")
        project_DOM = getObjectDOM( BASE_URI + 'projects/' + project_id )
        project_name = project_DOM.getElementsByTagName("name")[0].firstChild.data

        researcher_uri = project_DOM.getElementsByTagName( "researcher" )[0].getAttribute( "uri" )

        researcher = getResearcher( researcher_uri )
        researcher_email = researcher['email']
        researcher_user_name = researcher['user_name']
        # researcher_email = getResearcher( researcher_uri )

        share_worker = multiprocessing.Process(name="Worker_{0}".format(project_name), target=shareWorker, args=(project_name,project_id, researcher_email,researcher_user_name))

        share_workers.append( share_worker)
        share_worker.start()

    for w in share_workers:
        w.join()

def main():

    global api
    global options
    global nc_util

    parser = OptionParser()
    parser.add_option( "-u", "--username", help = "username of the current user", action = 'store', dest = 'username' )
    # parser.add_option( "-p", "--password", help = "password of the current user" )
    parser.add_option( "-s", "--stepURI", help = "the URI of the step that launched this script" )
    parser.add_option( "-i", "--projectids", help="The projectid(s) of the run you want to share. If multiple separate by comma." )
    parser.add_option( "-d", "--dataDir", help = "Root directory for sequencing runs ")
    parser.add_option( "-e", "--encrypt", help = "GPG encrypt data (yes/no)")
    parser.add_option( "-o","--shareonly", help = "Run sharing only (yes/no)")



    nextcloud_hostname = "ncie01.op.umcutrecht.nl"
    api_uri = "https://usf-lims.umcutrecht.nl/api/v2/"
    #parser.add_option( "-o", "--outname", help = "Output file name + path" )

    (options, otherArgs) = parser.parse_args()

    pw = getpass.getpass("Please enter the password for account {0}:\n".format(options.username))


    if options.stepURI: setupGlobalsFromURI( options.stepURI )
    else: setupGlobalsFromURI( api_uri )

    api = glsapiutil.glsapiutil()
    api.setHostname( HOSTNAME )
    api.setVersion( VERSION )
    api.setup( options.username, pw )

    nc_util = NextcloudUtil()
    nc_util.setHostname( nextcloud_hostname )
    nc_util.setup( options.username, pw )

    if options.stepURI:
        shareFromStep()
    elif options.projectids:
        shareFromProjectId()

if __name__ == "__main__":

    main()