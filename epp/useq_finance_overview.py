from genologics.entities import Step, ProtocolStep
from modules.useq_template import TEMPLATE_PATH,TEMPLATE_ENVIRONMENT,renderTemplate
from config import COST_DB,RUN_PROCESSES,ISOLATION_PROCESSES,LIBPREP_PROCESSES,ANALYSIS_PROCESSES
import re
import sys
import json
import urllib2

def getAllCosts():
	"""Retrieves costs from cost db"""
	costs_json = ""
	try:
		costs_json = urllib2.urlopen( COST_DB ).read()
	except urllib2.HTTPError, e:
		sys.exit(e.msg)
	except urllib2.URLError, e:
		sys.exit(e.read())
	except:
		sys.exit( str(sys.exc_type) + str(sys.exc_value) )

	costs = json.loads(costs_json)
	#Add costs that are not yet in the cost db
	costs['Mapping WGS'] = {'type_name' : 'Analysis', 'step_input' : 'Sample', 'date_costs' : {'2018-04-15' : 50} }
	costs['Mapping RNA'] = {'type_name' : 'Analysis', 'step_input' : 'Sample', 'date_costs' : {'2018-04-15' : 5} }
	costs['Germline SNV/InDel calling'] = {'type_name' : 'Analysis', 'step_input' : 'Sample', 'date_costs' : {'2018-04-15' : 0} }
	costs['CNV + SV calling'] = {'type_name' : 'Analysis', 'step_input' : 'Sample', 'date_costs' : {'2018-04-15' : 15} }
	costs['Somatic calling (tumor/normal pair)'] = {'type_name' : 'Analysis', 'step_input' : 'Sample', 'date_costs' : {'2018-04-15' : 10} }
	costs['Read count analysis (mRNA)'] = {'type_name' : 'Analysis', 'step_input' : 'Sample', 'date_costs' : {'2018-04-15' : 5} }
	costs['Differential expression analysis + figures (mRNA)'] = {'type_name' : 'Analysis', 'step_input' : 'Sample', 'date_costs' : {'2018-04-15' : 5} }

	costs_lower = dict( (k.lower(), v) for k,v in costs.iteritems())
	#Do some (unfortunately) neccessary name conversions
	costs_lower['libprep dna'] = costs_lower['truseq dna nano']
	costs_lower['truseq dna nano (manual)'] = costs_lower['truseq dna nano']
	costs_lower['truseq dna nano (automatic)'] = costs_lower['truseq dna nano']
	costs_lower['truseq rna stranded polya (manual)'] =costs_lower['truseq rna stranded polya']
	costs_lower['truseq rna stranded polya (automatic)'] =costs_lower['truseq rna stranded polya']
	costs_lower['libprep rna stranded polya'] = costs_lower['truseq rna stranded polya']
	costs_lower['truseq rna stranded ribo-zero'] = costs_lower['truseq rna stranded ribozero (human, mouse, rat)']
	costs_lower['libprep rna stranded ribo-zero'] = costs_lower['truseq rna stranded ribozero (human, mouse, rat)']
	costs_lower['open snp array'] = costs_lower['snp open array (60 snps)']
	# print costs_lower
	return costs_lower

def getNearestBillingDate(all_costs, step ,step_date):
	billing_date = ''
	for date in sorted(all_costs[ step ][ 'date_costs'].keys() ):
		if date <= step_date:
			billing_date = date
	return billing_date

def getStepProtocol(lims, step_id=None, step_uri=None):
	protocol_name = None
	if step_uri:
		step_config = Step(lims, uri=step_uri).configuration
		protocol_uri = re.sub("\/steps\/\d+","",step_config.uri)
		protocol_name = ProtocolStep(lims, uri=protocol_uri).name
	else:
		step_config = Step(lims, id=step_id).configuration
		protocol_uri = re.sub("\/steps\/\d+","",step_config.uri)
		protocol_name = ProtocolStep(lims, uri=protocol_uri).name
	return protocol_name


def getSeqFinance(lims, step_uri):
	"""Calculates the costs for all sequencing runs included in the step"""
	seq_finance = []
	all_costs = getAllCosts()

	step_details = Step(lims, uri=step_uri).details
	runs = {}
	#Get the input artifacts (which is a pool of samples)
	for io_map in step_details.input_output_maps:
		pool = io_map[0]['uri']
		runs[pool.id] = {
			'errors' : set(),
			'name' : None,'id' : None,'open_date' : None,'nr_samples' : 0,'first_submission_date' : None,'received_date' : set(), #project fields
			'pool' : pool.id,
			'lims_runtype' : None,		'requested_runtype' : set(),		'run_costs' : None,		'run_date' : None,			'succesful' : None, #run fields
			'lims_isolation' : set(),	'type' : set(),						'isolation_costs' : 0,	'isolation_date' : set(), #isolation fields
			'lims_library_prep' : set(),'requested_library_prep' : set(),	'libprep_costs' : 0,	'libprep_date' : set(), #libprep fields
			'lims_analysis' : set(),	'requested_analysis' : set(),		'analysis_costs' : 0,	'analysis_date' : set(), #analysis fields
			'total_costs' :0,
			'contact_name' : None,'contact_email' : None,'lab_name' : None,'budget_nr' : None,'institute' : None,'postalcode' : None,'city' : None,'country' : None,'department' : None,'street' : None,

		}

		for sample in pool.samples:
			runs[pool.id]['nr_samples'] += 1
			runs[pool.id]['received_date'].add(sample.date_received)
			runs[pool.id]['type'].add(sample.udf['Sample Type'])
			runs[pool.id]['requested_library_prep'].add(sample.udf['Library prep kit'])
			runs[pool.id]['requested_runtype'].add(sample.udf['Sequencing Runtype'])
			# runs[pool.id]['requested_analysis'].add(sample.udf['Analysis'])

			sample_artifacts = lims.get_artifacts(samplelimsid=sample.id)
			for sample_artifact in sample_artifacts:

				if not sample_artifact.parent_process: continue
				process_name = sample_artifact.parent_process.type.name

				if process_name in ISOLATION_PROCESSES:
					isolation_type = "{0} isolation".format(sample_artifact.udf['US Isolation Type'].split(" ")[0].lower())
					billing_date = getNearestBillingDate(all_costs, isolation_type , sample_artifact.parent_process.date_run)
					runs[pool.id]['isolation_costs'] += float(all_costs[ isolation_type ][ 'date_costs' ][ billing_date ])
					runs[pool.id]['total_costs']+= float(all_costs[ isolation_type ][ 'date_costs' ][ billing_date ])
					runs[pool.id]['lims_isolation'].add(sample_artifact.udf['US Isolation Type'])
					runs[pool.id]['isolation_date'].add(sample_artifact.parent_process.date_run)

					if isolation_type == 'rna isolation' and sample.udf['Sample Type'] != 'RNA unisolated':
						runs[pool.id]['errors'].add("Isolation type {0} in LIMS doesn't match sample type {1}".format(isolation_type, sample.udf['Sample Type']))
					elif isolation_type == 'dna isolation' and sample.udf['Sample Type'] != 'DNA unisolated':
						runs[pool.id]['errors'].add("Isolation type {0} in LIMS doesn't match sample type {1}".format(isolation_type, sample.udf['Sample Type']))

				elif process_name in LIBPREP_PROCESSES:
					protocol_name = getStepProtocol(lims, step_id=sample_artifact.parent_process.id)
					lims_library_prep = protocol_name.split("-",1)[1].lower().strip()
					runs[pool.id]['lims_library_prep'].add(lims_library_prep)

					billing_date = getNearestBillingDate(all_costs, lims_library_prep , sample_artifact.parent_process.date_run)
					runs[pool.id]['libprep_costs'] += float(all_costs[ lims_library_prep][ 'date_costs' ][ billing_date ])
					runs[pool.id]['total_costs'] += float(all_costs[ lims_library_prep][ 'date_costs' ][ billing_date ])
					runs[pool.id]['libprep_date'].add(sample_artifact.parent_process.date_run)

					if sample.udf['Library prep kit'] == 'Truseq RNA stranded polyA' and 'libprep rna stranded polya' not in runs[pool.id]['lims_library_prep']:
						runs[pool.id]['errors'].add("Libprep type {0} in LIMS doesn't match libprep type {1}".format(runs[pool.id]['lims_library_prep'],sample.udf['Library prep kit']))

					elif sample.udf['Library prep kit'] == 'Truseq RNA stranded ribo-zero' and 'libprep rna stranded ribo-zero' not in runs[pool.id]['lims_library_prep'] :
						runs[pool.id]['errors'].add("Libprep type {0} in LIMS doesn't match libprep type {1}".format(runs[pool.id]['lims_library_prep'],sample.udf['Library prep kit']))

					elif sample.udf['Library prep kit'] == 'Truseq DNA nano' and 'libprep dna' not in runs[pool.id]['lims_library_prep'] :
						runs[pool.id]['errors'].add("Libprep type {0} in LIMS doesn't match libprep type {1}".format(runs[pool.id]['lims_library_prep'],sample.udf['Library prep kit']))

				elif process_name in RUN_PROCESSES and not runs[pool.id]['lims_runtype']:
					protocol_name = getStepProtocol(lims, step_id=sample_artifact.parent_process.id)
					runs[pool.id]['lims_runtype'] = protocol_name.split("-",1)[1].lower().strip()
					requested_runtype = sample.udf['Sequencing Runtype'].lower()
					billing_date = getNearestBillingDate(all_costs, requested_runtype , sample_artifact.parent_process.date_run)
					runs[pool.id]['run_costs'] = float(all_costs[ requested_runtype ][ 'date_costs' ][ billing_date ])
					runs[pool.id]['total_costs'] += float(all_costs[ requested_runtype ][ 'date_costs' ][ billing_date ])
					runs[pool.id]['run_date'] = sample_artifact.parent_process.date_run

					if runs[pool.id]['lims_runtype'].split(" ")[0] not in ",".join(runs[pool.id]['requested_runtype']).lower():
						runs[pool.id]['errors'].add("Run type {0} in LIMS doesn't match run type {1}".format(runs[pool.id]['lims_runtype'],",".join(runs[pool.id]['requested_runtype'])))
				elif process_name in ANALYSIS_PROCESSES:
					billing_date = getNearestBillingDate(all_costs, 'mapping wgs' , sample_artifact.parent_process.date_run)
					runs[pool.id]['analysis_date'].add(sample_artifact.parent_process.date_run)
					analysis_steps =['Raw data (FastQ)']
					analysis_costs = 0
					if sample_artifact.parent_process.udf['Mapping']:
						analysis_steps.append('Mapping')
						if sample.udf['Sample Type'].startswith('RNA'):
							analysis_costs += float(all_costs['mapping rna']['date_costs'][ billing_date ])
						else:
							analysis_costs += float(all_costs['mapping wgs']['date_costs'][ billing_date ])
					if sample_artifact.parent_process.udf['Germline SNV/InDel calling']:
						analysis_steps.append('Germline SNV/InDel calling')
						analysis_costs += float(all_costs['germline snv/indel calling']['date_costs'][ billing_date ])
					if sample_artifact.parent_process.udf['Read count analysis (mRNA)']:
						analysis_steps.append('Read count analysis (mRNA)')
						analysis_costs += float(all_costs['read count analysis (mrna)']['date_costs'][ billing_date ])
					if sample_artifact.parent_process.udf['Differential expression analysis + figures (mRNA)']:
						analysis_steps.append('Differential expression analysis + figures (mRNA)')
						analysis_costs += float(all_costs['differential expression analysis + figures (mrna)']['date_costs'][ billing_date ])
					if sample_artifact.parent_process.udf['CNV + SV calling']:
						analysis_steps.append('CNV + SV calling')
						analysis_costs += float(all_costs['cnv + sv calling']['date_costs'][ billing_date ])
					if sample_artifact.parent_process.udf['Somatic calling (tumor/normal pair)']:
						analysis_steps.append('Somatic calling (tumor/normal pair)')
						analysis_costs += float(all_costs['somatic calling (tumor/normal pair)']['date_costs'][ billing_date ])

					runs[pool.id]['requested_analysis'].add(",".join(sorted(sample.udf['Analysis'].split(","))))
					runs[pool.id]['lims_analysis'].add(",".join( sorted( analysis_steps) ))
					runs[pool.id]['analysis_costs'] += analysis_costs
					runs[pool.id]['total_costs'] += analysis_costs
					if runs[pool.id]['requested_analysis'] != runs[pool.id]['lims_analysis']:
						runs[pool.id]['errors'].add("Analysis type {0} in LIMS doesn't match analysis {1}".format(runs[pool.id]['lims_analysis'], runs[pool.id]['requested_analysis']))

			#Get billing specific info
			if not runs[pool.id]['name'] :
				runs[pool.id]['first_submission_date'] = sample.date_received
				if 'Sequencing Succesful' in pool.udf : runs[pool.id]['succesful'] = pool.udf['Sequencing Succesful']
				runs[pool.id]['name'] = sample.project.name
				runs[pool.id]['id'] = sample.project.id
				runs[pool.id]['open_date'] = sample.project.open_date
				runs[pool.id]['contact_name'] = sample.project.researcher.first_name + " " + sample.project.researcher.last_name
				runs[pool.id]['contact_email'] = sample.project.researcher.email
				runs[pool.id]['lab_name'] = sample.project.researcher.lab.name
				runs[pool.id]['budget_nr'] = sample.udf['Budget Number']
				runs[pool.id]['institute'] = sample.project.researcher.lab.billing_address['institution']
				runs[pool.id]['postalcode'] = sample.project.researcher.lab.billing_address['postalCode']
				runs[pool.id]['city'] = sample.project.researcher.lab.billing_address['city']
				runs[pool.id]['country'] = sample.project.researcher.lab.billing_address['country']
				runs[pool.id]['department'] = sample.project.researcher.lab.billing_address['department']
				runs[pool.id]['street'] = sample.project.researcher.lab.billing_address['street']

	return renderTemplate('seq_finance_overview_template.csv', {'runs':runs})
def getSnpFinance(lims, step_uri):
	seq_finance = []
	all_costs = getAllCosts()

	step_details = Step(lims, uri=step_uri).details

	runs = {}
	#Get the input artifacts (which is a pool of samples)
	for io_map in step_details.input_output_maps:
		pool = io_map[0]['uri']
		for sample in pool.samples:
			budget_nr = sample.udf['Budget Number']
			if sample.project.id + budget_nr not in runs:
				runs[ sample.project.id + budget_nr ] ={
					'errors' : set(),
					'name' : sample.project.name,
					'id' : sample.project.id,
					'open_date' : sample.project.open_date,
					'nr_samples' : 0,
					'first_submission_date' : None,
					'received_date' : set(), #project fields
					'description' : set(),
					'type' : set(),
					'isolation_costs' : 0,
					'plate_costs' : 0,
					'total_costs' :0,
					'contact_name' : sample.project.researcher.first_name + " " + sample.project.researcher.last_name,
					'contact_email' : sample.project.researcher.email,
					'lab_name' : sample.project.researcher.lab.name,
					'budget_nr' : budget_nr,
					'institute' : sample.project.researcher.lab.billing_address['institution'],
					'postalcode' : sample.project.researcher.lab.billing_address['postalCode'],
					'city' : sample.project.researcher.lab.billing_address['city'],
					'country' : sample.project.researcher.lab.billing_address['country'],
					'department' : sample.project.researcher.lab.billing_address['department'],
					'street' : sample.project.researcher.lab.billing_address['street']
				}


			runs[sample.project.id + budget_nr]['nr_samples'] += 1
			runs[sample.project.id + budget_nr]['received_date'].add(sample.date_received)
			runs[sample.project.id + budget_nr]['type'].add(sample.udf['Sample Type'])
			runs[sample.project.id + budget_nr]['description'].add(sample.udf['Description'])
			billing_date = getNearestBillingDate(all_costs, 'open snp array' , sample.date_received)
			runs[sample.project.id + budget_nr]['plate_costs'] = float(all_costs['open snp array']['date_costs'][ billing_date ])
			if not runs[sample.project.id + budget_nr]['total_costs']:
				runs[sample.project.id + budget_nr]['total_costs'] += runs[sample.project.id + budget_nr]['plate_costs']

			if sample.udf['Sample Type'] == 'DNA unisolated':
				runs[sample.project.id + budget_nr]['isolation_costs'] += float( all_costs['dna isolation'][ 'date_costs' ][ billing_date ] )
				runs[sample.project.id + budget_nr]['total_costs'] += float( all_costs['dna isolation'][ 'date_costs' ][ billing_date ] )
			elif sample.udf['Sample Type'] == 'RNA unisolated':
				runs[sample.project.id + budget_nr]['isolation_costs'] += float( all_costs['rna isolation'][ 'date_costs' ][ billing_date ] )
				runs[sample.project.id + budget_nr]['total_costs'] += float( all_costs['rna isolation'][ 'date_costs' ][ billing_date ] )

	return renderTemplate('snp_finance_overview_template.csv', {'runs':runs})

def run(lims, step_uri, output_file):
	"""Runs the getSeqFinance or the getSnpFinance depending on the protocol the step is in"""

	protocol_name = getStepProtocol(lims,step_uri=step_uri)

	if protocol_name.startswith("USEQ - Post Sequencing"):
		finance_table = getSeqFinance(lims,step_uri)
		output_file.write(finance_table.encode('utf-8'))
	elif protocol_name.startswith("USEQ - Post Fingerprinting"):
		finance_table = getSnpFinance(lims, step_uri)
		output_file.write(finance_table.encode('utf-8'))
