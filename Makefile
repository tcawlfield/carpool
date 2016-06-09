all: lambda.zip

PY_FILES := $(shell find ./ -type f -name '*.py')

lambda.zip: $(PY_FILES)
	zip $@ $^

upload: lambda.zip
	aws lambda update-function-code --function-name=carpool_ss --zip-file fileb://lambda.zip

.PHONY: upload
