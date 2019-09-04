exec_name_prefix = ocrd-anybaseocr
testdir = ""

export

SHELL = /bin/bash
PYTHON = python
PIP = pip
LOG_LEVEL = INFO
PYTHONIOENCODING=utf8

# BEGIN-EVAL makefile-parser --make-help Makefile

help:
	@echo ""
	@echo "  Targets"
	@echo ""
	@echo "    deps           Install python deps via pip"
	@echo "    install        Install"
	@echo "    repo/assets    Clone OCR-D/assets to ./repo/assets"
	@echo "    assets-clean   Remove assets"
	@echo "    assets         Setup test assets"
	@echo "    test           Run all tests"
	@echo "    test-binarize  Test binarization"
	@echo "    test-deskew    Test deskewing"
	@echo "    test-crop      Test cropping"
	@echo ""
	@echo "  Variables"
	@echo ""

# END-EVAL

# Install python deps via pip
deps:
	$(PIP) install -r requirements.txt

# Install
install:
	$(PIP) install .

#
# Assets
#

# Download sample model
#model: ocrd_anybaseocr/models/latest_net_G.pth

#ocrd_anybaseocr/models/latest_net_G.pth:
#	wget -O"$@" "https://cloud.dfki.de/owncloud/index.php/s/3zKza5sRfQB3ygy/download"

# Clone OCR-D/assets to ./repo/assets
#repo/assets:
#	mkdir -p $(dir $@)
#	git clone https://github.com/OCR-D/assets "$@"

# Remove assets
#assets-clean:
#	rm -rf $(testdir)/assets

# Setup test assets
#assets: repo/assets
#	mkdir -p $(testdir)/assets
#	cp -r -t $(testdir)/assets repo/assets/data/*

#
# Tests
#

# Run all tests
#test: test-binarize test-deskew test-crop test-tiseg test-textline test-block-segmentation test-layout-analysis

# Run minimum sample
test: test-binarize

# Test binarization
test-binarize: 
	cd $(testdir)/ocrd_anybaseocr && $(exec_name_prefix)-binarize -m mets.xml -I OCR-D-IMG -O OCR-D-IMG-BIN

# Test deskewing
test-deskew: 
	cd $(testdir)/ocrd_anybaseocr && $(exec_name_prefix)-deskew -m mets.xml -I OCR-D-IMG-BIN -O OCR-D-IMG-DESKEW

# Test cropping
test-crop: 
	cd $(testdir)/ocrd_anybaseocr && $(exec_name_prefix)-crop -m mets.xml -I OCR-D-IMG-DESKEW -O OCR-D-IMG-CROP

# Test text/non-text segmentation
test-tiseg: 
	cd $(testdir)/ocrd_anybaseocr && $(exec_name_prefix)-tiseg -m mets.xml -I OCR-D-IMG-CROP -O OCR-D-IMG-TISEG

# Test textline extraction
test-textline: 
	cd $(testdir)/ocrd_anybaseocr && $(exec_name_prefix)-textline -m mets.xml -I OCR-D-IMG-TISEG -O OCR-D-IMG-TL

# Test block segmentation
test-block-segmentation: 
	cd $(testdir)/ocrd_anybaseocr && CUDA_VISIBLE_DEVICES=0 && $(exec_name_prefix)-block-segmentation -m mets_block.xml -I OCR-D-BLOCK -O OCR-D-BLOCK-SEGMENT -p params.json

# Test document structure analysis
test-layout-analysis: 
	cd $(testdir)/ocrd_anybaseocr && CUDA_VISIBLE_DEVICES=0 && $(exec_name_prefix)-layout-analysis -m mets_docanalysis.xml -I OCR-D-DOC -O OCR-D-IMG-LAYOUT -p params.json