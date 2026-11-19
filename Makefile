.PHONY: start stop status list check
start:
	./bin/lfcs start
stop:
	./bin/lfcs stop
status:
	./bin/lfcs status
list:
	./bin/lfcs list
check:
	./tests/static-check.sh
