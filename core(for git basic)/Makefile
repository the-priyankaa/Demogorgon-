.PHONY: run test proof clean install uninstall

run:
	PYTHONPATH=src python3 -m stdedit.main $(FILE) $(ARGS)

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

proof:
	bash deps-proof.sh

clean:
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	rm -f deps-proof.txt

install:
	PYTHONPATH=src python3 -m stdedit.install install

uninstall:
	PYTHONPATH=src python3 -m stdedit.install uninstall
