import json
import time
import random
import math
from string import Template

from flask import Flask, request, Response, render_template
from Queue import Queue

import pyorient

from sklearn import preprocessing
from sklearn import svm

import numpy as np
import random

app = Flask(__name__)

q = Queue()

def point_distance(lat1, lng1, lat2, lng2):
	return ((lat1-lat2)**2.0 + (lng1-lng2)**2.0)**(0.5)


def event_stream():
    while True:
        result = q.get()
        yield 'data: %s\n\n' % str(result)

@app.route('/eventSource/')
def sse_source():
    return Response(
            event_stream(),
            mimetype='text/event-stream')

def getData(lat1,lng1,lat2,lng2):

	print 'received lat: ' + lat1 + ', ' + lat2
	print 'received lon: ' + lng1 + ', ' + lng2
	
	#ORIENTDB IMPLEMENTATION
	client = pyorient.OrientDB("localhost", 2424)
	session_id = client.connect("root", "admin")

	db_name = "soufun"

	if client.db_exists( db_name, pyorient.STORAGE_TYPE_MEMORY ):
		client.db_open( db_name, "admin", "admin" )
	else:
		print "database does not exist!"
		sys.exit()

	s = Template('SELECT FROM Listing WHERE latitude BETWEEN $lat1 AND $lat2 AND longitude BETWEEN $lng1 AND $lng2')
	
	# TO IMPLEMENT: COMPOSITE KEY SEARCH
	#s = Template('SELECT * FROM INDEX:Listing.latitude_longitude WHERE key BETWEEN [$lat1, $lng1] AND [$lat2, $lng2]')
	
	records = client.command(s.safe_substitute(lat1 = lat1, lng1 = lng1, lat2 = lat2, lng2 = lng2))

	random.shuffle(records)
	records = records[:1000]

	client.db_close()

	return records



@app.route("/")
def index():
    return render_template("index.html")

@app.route('/updateData/')
def updateData():


	q.put("starting data query...")

	lat1 = str(request.args.get('lat1'))
	lng1 = str(request.args.get('lng1'))
	lat2 = str(request.args.get('lat2'))
	lng2 = str(request.args.get('lng2'))

	w = float(request.args.get('w'))
	h = float(request.args.get('h'))
	res = float(request.args.get('res'))


	analysisType = request.args.get('type')
	print "type: " + analysisType

	print analysisType == 'Int'

	records = getData(lat1, lng1, lat2, lng2)

	recordsDict = {"points":{"type":"FeatureCollection","features":[]}}

	for record in records:
		recordDict = {"type":"Feature","properties":{},"geometry":{"type":"Point"}}
		recordDict["id"] = record._rid
		recordDict["properties"]["name"] = record.title
		recordDict["properties"]["price"] = record.price
		recordDict["geometry"]["coordinates"] = [record.longitude, record.latitude]

		recordsDict["points"]["features"].append(recordDict)

	#DUMMY DATA IMPLEMENTATION
	# with open("static/data.txt", 'r') as f:
	# 	recordsDict = json.loads(f.read())

	print "acquired!"

	q.put("finished data query...")\

	if analysisType == "HM":
		#implement Heatmap code
		q.put("starting heatmap...")

		numW = int(math.floor(w/res))
		numH = int(math.floor(h/res))

		offsetLeft = (w - numW * res) / 2.0 ;
		offsetTop = (h - numH * res) / 2.0 ;

		recordsDict["analysis"] = []

		coords = []

		for j in range(numH):
			for i in range(numW):

				newItem = {}

				newItem['x'] = offsetLeft + i*res
				newItem['y'] = offsetTop + j*res
				newItem['width'] = res-1
				newItem['height'] = res-1

				lat = np.interp(float(j)/float(numH),[0,1],[lat2,lat1])
				lng = np.interp(float(i)/float(numW),[0,1],[lng1,lng2])

				val = 0

				for record in records:
					dist = point_distance(record.latitude, record.longitude, lat, lng)
					#print dist
					if dist < 0.03:
						val = val + 1

				coords.append(val)
				newItem['val'] = val

				recordsDict["analysis"].append(newItem)

		maxVal = np.amax(coords)

		for item in recordsDict["analysis"]:
			item["val"] = item["val"] / float(maxVal)

		q.put("finished heatmap...")




	if analysisType == "Int":

		q.put("starting interpolation...")

		numW = int(math.floor(w/res))
		numH = int(math.floor(h/res))

		offsetLeft = (w - numW * res) / 2.0 ;
		offsetTop = (h - numH * res) / 2.0 ;

		# ML IMPLEMENTATION
		featureData = []
		targetData = []

		for record in records:
			featureData.append([record.latitude, record.longitude])
			targetData.append(record.price)

		X = np.asarray(featureData, dtype='float')
		y = np.asarray(targetData, dtype='float')

		num = int(len(targetData) * .7)

		X_train = X[:num]
		X_val = X[num:]

		y_train = y[:num]
		y_val = y[num:]

		#mean 0, variance 1
		scaler = preprocessing.StandardScaler().fit(X_train)
		X_train_scaled = scaler.transform(X_train)


		model = svm.SVR(C=10000000, epsilon=.00001, kernel='rbf', cache_size=2000)
		model.fit(X_train_scaled, y_train)

		recordsDict["analysis"] = []

		coords = []

		for j in range(numH):
			for i in range(numW):

				newItem = {}

				newItem['x'] = offsetLeft + i*res
				newItem['y'] = offsetTop + j*res
				newItem['width'] = res-1
				newItem['height'] = res-1

				lat = np.interp(float(j)/float(numH),[0,1],[lat2,lat1])
				lng = np.interp(float(i)/float(numW),[0,1],[lng1,lng2])

				testData = [[lat, lng]]
				X_test = np.asarray(testData, dtype='float')
				X_test_scaled = scaler.transform(X_test)
				prediction = model.predict(X_test_scaled)

				val = max(prediction[0], 0)

				coords.append(val)
				newItem['val'] = val

				recordsDict["analysis"].append(newItem)

		maxVal = np.amax(coords)

		for item in recordsDict["analysis"]:
			item["val"] = item["val"] / float(maxVal)

		q.put("finished interpolation...")

	q.put('idle')
	#pass GeoJSON data back to D3
	return json.dumps(recordsDict)

#MAKE SURE THREADING IS ENAMBLED FOR SSE TO FUNCTION!
if __name__ == "__main__":
    app.run(host='0.0.0.0',port=5000,debug=True,threaded=True)