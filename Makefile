all: lambda.zip

lambda.zip: *.py
	zip $@ $^

upload: lamdba.zip
	aws lambda update-function-code --function-name=carpool_ss --zip-file fileb://lambda.zip

.PHONY: upload
