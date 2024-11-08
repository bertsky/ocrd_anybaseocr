import sys
import pickle
import numpy as np 
import warnings
warnings.filterwarnings('ignore',category=FutureWarning) 
from collections import defaultdict
from ..constants import OCRD_TOOL

import click
from ocrd.decorators import ocrd_cli_options, ocrd_cli_wrap_processor

from ocrd import Processor
from ocrd_modelfactory import page_from_file
from ocrd_models.ocrd_page import to_xml
from ocrd_utils import getLogger, assert_file_grp_cardinality
from ocrd_models import ocrd_mets

from pathlib import Path
import ocrolib
from PIL import Image

from lxml import etree as ET

from ocrd_models.ocrd_mets import OcrdMets
from ocrd_models.constants import (
    NAMESPACES as NS,
    TAG_METS_AGENT,
    TAG_METS_DIV,
    TAG_METS_FILE,
    TAG_METS_FILEGRP,
    TAG_METS_FILESEC,
    TAG_METS_FPTR,
    TAG_METS_METSHDR,
    TAG_METS_STRUCTMAP,
    IDENTIFIER_PRIORITY,
    TAG_MODS_IDENTIFIER,
    METS_XML_EMPTY,
)

from ..tensorflow_importer import tf
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing.image import ImageDataGenerator

TAG_METS_STRUCTLINK = '{%s}structLink' % NS['mets']
TAG_METS_SMLINK = '{%s}smLink' % NS['mets']


TOOL = 'ocrd-anybaseocr-layout-analysis'


class OcrdAnybaseocrLayoutAnalyser(Processor):

    def __init__(self, *args, **kwargs):
        
        self.last_result = [] 
        self.logID = 0 # counter for new key
        self.logIDs = defaultdict(int) # dict to keep track of previous keys for labels other then chapter or section
        self.log_id = 0 # var to keep the current ongoing key
        self.log_links = {}
        self.first = None
        
        kwargs['ocrd_tool'] = OCRD_TOOL['tools'][TOOL]
        kwargs['version'] = OCRD_TOOL['version']
        super(OcrdAnybaseocrLayoutAnalyser, self).__init__(*args, **kwargs)
        if hasattr(self, 'output_file_grp') and hasattr(self, 'parameter'):
            # processing context
            self.setup()

    def setup(self):
        LOG = getLogger('OcrdAnybaseocrLayoutAnalyser')
        model_path = Path(self.resolve_resource(self.parameter['model_path']))
        class_mapper_path = Path(self.resolve_resource(self.parameter['class_mapping_path']))
        if not model_path.exists():
            LOG.critical("Layout classfication `model_path` was not found at '%s'", model_path)
            sys.exit(1)
        LOG.info('Loading model from file %s', str(model_path))
        self.model = self.create_model(str(model_path))
        # load the mapping
        pickle_in = open(str(class_mapper_path), "rb")
        class_indices = pickle.load(pickle_in)
        self.label_mapping = dict((v,k) for k,v in class_indices.items())

    def create_model(self, path):
        #model_name='inception_v3', def_weights=True, num_classes=34, input_size=(600, 500, 1)):
        '''load Tensorflow model from path'''
        return load_model(path)

    def predict(self, img_array):
        # shape should be 1,600,500 for keras
        pred = self.model.predict(img_array)
        pred = np.array(pred)
        # multi-label predictions
        if len(pred.shape)>2:        
            pred = np.squeeze(pred)
            pred = pred.T
        preds = (pred>=0.5)
        predictions = []
        for index, cls in enumerate(preds):
            if cls:
                predictions.append(self.label_mapping[index])
        
        if len(predictions) == 0:
            # if no prediction get the maximum one
            predictions.append(self.label_mapping[np.argmax(pred)])
            #predictions.append('page') # default label
        return predictions

    def img_resize(self, image_path):
        size = 600, 500
        img = Image.open(image_path)
        return img.thumbnail(size, Image.LANCZOS)    
    
    def write_to_mets(self, result, pageID):  
        
        for i in result:   
            create_new_logical = False
            # check if label is page skip 
            if i !="page":
            
            # if not page, chapter and section then its something old
                
                if i!="chapter" and i!="section":
        
                    if i in self.last_result:
                        self.log_id = self.logIDs[i]
                    else:
                        create_new_logical = True

                    if i =='binding':
                        parent_node = self.log_map
                    
                    if i=='cover' or i=='endsheet' or i=='paste_down':

                        # get the link for master node
                        parent_node = self.log_links['binding']

                    else:
                        
                        if self.first is not None and i!='title_page':
                            parent_node = self.log_links[self.first]
                        else:
                            parent_node = self.log_map
                            
                else:
                    create_new_logical = True
                    
                    if self.first is None:
                        self.first = i
                        parent_node = self.log_map
                            
                    else:
                        if self.first == i:
                            parent_node = self.log_map
                        else:
                            parent_node = self.log_links[self.first]
                            
                    
                if create_new_logical:
        
                    log_div = ET.SubElement(parent_node, TAG_METS_DIV)
                    log_div.set('TYPE', str(i))            
                    log_div.set('ID', "LOG_"+str(self.logID))
                      
                    self.log_links[i] = log_div # store the link 
                    #if i!='chapter' and i!='section':
                    self.logIDs[i] = self.logID
                    self.log_id = self.logID
                    self.logID += 1
                                        
            
            else:
                if self.logIDs['chapter'] > self.logIDs['section']:
                    self.log_id = self.logIDs['chapter']
                 
                if self.logIDs['section'] > self.logIDs['chapter']:
                    self.log_id = self.logIDs['section']
                    
                if self.logIDs['chapter']==0 and self.logIDs['section']==0:
                    
                    # if both chapter and section dont exist
                    if self.first is None:
                        self.first = 'chapter'
                        parent_node = self.log_map
                    # rs: not sure about the remaining branches (cf. #73)
                    elif self.first == i:
                        parent_node = self.log_map
                    else:
                        parent_node = self.log_links[self.first]
                            
                    log_div = ET.SubElement(parent_node, TAG_METS_DIV)
                    log_div.set('TYPE', str(i))            
                    log_div.set('ID', "LOG_"+str(self.logID))
                      
                    self.log_links[i] = log_div # store the link 
                    #if i!='chapter' and i!='section':
                    self.logIDs[i] = self.logID
                    self.log_id = self.logID
                    self.logID += 1                    
                
                
            smLink = ET.SubElement(self.link, TAG_METS_SMLINK)
            smLink.set('{'+NS['xlink']+'}'+'to', pageID)
            smLink.set('{'+NS['xlink']+'}'+'from', "LOG_"+str(self.log_id))
        
        self.last_result = result
    
    def create_logmap_smlink(self, workspace):
        LOG = getLogger('OcrdAnybaseocrLayoutAnalyser')
        el_root = self.workspace.mets._tree.getroot()
        log_map = el_root.find('mets:structMap[@TYPE="LOGICAL"]', NS)
        if log_map is None:
            log_map = ET.SubElement(el_root, TAG_METS_STRUCTMAP)
            log_map.set('TYPE', 'LOGICAL')
        else:
            LOG.info('LOGICAL structMap already exists, adding to it')
        link = el_root.find('mets:structLink', NS)
        if link is None:
            link = ET.SubElement(el_root, TAG_METS_STRUCTLINK)
        self.link = link
        self.log_map = log_map                        

    def process(self):
        LOG = getLogger('OcrdAnybaseocrLayoutAnalyser')
        if not tf.test.is_gpu_available():
            LOG.error("Your system has no CUDA installed. No GPU detected.")
        assert_file_grp_cardinality(self.input_file_grp, 1)
        assert_file_grp_cardinality(self.output_file_grp, 1)

        for input_file in self.input_files:
            page_id = input_file.pageId or input_file.ID
            pcgts = page_from_file(self.workspace.download_file(input_file))
            page = pcgts.get_Page()
            LOG.info("INPUT FILE %s", page_id)
            page_image, page_coords, _ = self.workspace.image_from_page(page, page_id, feature_selector='binarized')
            img_array = ocrolib.pil2array(page_image.resize((500, 600), Image.LANCZOS))
            img_array = img_array / 255
            img_array = img_array[np.newaxis, :, :, np.newaxis]            
            results = self.predict(img_array)
            LOG.info(results)
            #self.workspace.mets.set_physical_page_for_file(input_file.pageId, input_file)
            self.create_logmap_smlink(pcgts)
            self.write_to_mets(results, input_file.pageId)

@click.command()
@ocrd_cli_options
def cli(*args, **kwargs):
    return ocrd_cli_wrap_processor(OcrdAnybaseocrLayoutAnalyser, *args, **kwargs)
