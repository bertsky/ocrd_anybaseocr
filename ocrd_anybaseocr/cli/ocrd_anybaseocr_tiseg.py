#!/usr/bin/python

# Author: Saqib Bukhari
# Email: Saqib.Bukhari@dfki.de
# Paper: Syed Saqib Bukhari, Faisal Shafait, Thomas M. Breuel, "Improved document image segmentation algorithm using multiresolution morphology," Proc. SPIE 7874, Document Recognition and Retrieval XVIII, 78740D (24 January 2011);

# "Syed Saqib Bukhari, Ahmad Kadi, Mohammad Ayman Jouneh, Fahim Mahmood Mir, Andreas Dengel, “anyOCR: An Open-Source OCR System for Historical Archives”, The 14th IAPR International Conference on Document Analysis and Recognition (ICDAR 2017), Kyoto, Japan, 2017.
# URL - https://www.dfki.de/fileadmin/user_upload/import/9512_ICDAR2017_anyOCR.pdf


import copy
import json
import os
from pathlib import Path
import sys
import math
import click
from PIL import Image
from scipy import ndimage
import numpy as np
import shapely
import ocrolib
from tensorflow.keras.models import load_model
#from keras_segmentation.models.unet import resnet50_unet
from ocrd import Processor
from ocrd_modelfactory import page_from_file
from ocrd_models.ocrd_page import to_xml, AlternativeImageType
from ocrd_utils import (
    getLogger,
    concat_padded,
    MIMETYPE_PAGE,
    coordinates_for_segment,
    points_from_polygon,
    make_file_id,
    assert_file_grp_cardinality,
)
from ocrd.decorators import ocrd_cli_options, ocrd_cli_wrap_processor
from ..constants import OCRD_TOOL

TOOL = 'ocrd-anybaseocr-tiseg'

class OcrdAnybaseocrTiseg(Processor):

    def __init__(self, *args, **kwargs):
        kwargs['ocrd_tool'] = OCRD_TOOL['tools'][TOOL]
        kwargs['version'] = OCRD_TOOL['version']
        super(OcrdAnybaseocrTiseg, self).__init__(*args, **kwargs)
        if hasattr(self, 'output_file_grp') and hasattr(self, 'parameter'):
            # processing context
            self.setup()

    def setup(self):
        LOG = getLogger('OcrdAnybaseocrTiseg')
        self.model = None
        if self.parameter['use_deeplr']:

            model_weights = self.resolve_resource(self.parameter['seg_weights'])
            #model = resnet50_unet(n_classes=self.parameter['classes'], input_height=self.parameter['height'], input_width=self.parameter['width'])
            #model.load_weights(model_weights)
            self.model = load_model(model_weights)
            LOG.info('Loaded segmentation model')
            
    def process(self):
        LOG = getLogger('OcrdAnybaseocrTiseg')

        assert_file_grp_cardinality(self.input_file_grp, 1)
        assert_file_grp_cardinality(self.output_file_grp, 1)

        for input_file in self.input_files:
            page_id = input_file.pageId or input_file.ID

            pcgts = page_from_file(self.workspace.download_file(input_file))
            self.add_metadata(pcgts)

            page = pcgts.get_Page()
            LOG.info("INPUT FILE %s", input_file.pageId or input_file.ID)

            if self.parameter['use_deeplr']:
                kwargs = {'feature_filter': 'binarized,deskewed,cropped'}
            else:
                # _should_ also be deskewed and cropped, but no need to enforce that here
                kwargs = {'feature_selector': 'binarized'}
            page_image, page_coords, page_image_info = self.workspace.image_from_page(
                page, page_id, **kwargs)

            self._process_segment(page, page_image, page_coords, page_id, input_file)

            file_id = make_file_id(input_file, self.output_file_grp)
            pcgts.set_pcGtsId(file_id)
            self.workspace.add_file(
                ID=file_id,
                file_grp=self.output_file_grp,
                pageId=input_file.pageId,
                mimetype=MIMETYPE_PAGE,
                local_filename=os.path.join(self.output_file_grp, file_id + '.xml'),
                content=to_xml(pcgts).encode('utf-8'),
            )

    def _process_segment(self, page, page_image, page_coords, page_id, input_file):
        LOG = getLogger('OcrdAnybaseocrTiseg')

        if self.model:

            I = ocrolib.pil2array(page_image.resize((800, 1024), Image.LANCZOS))
            I = np.array(I)[np.newaxis, :, :, :]
            LOG.info('I shape %s', I.shape)
            if len(I.shape)<3:
                print('Wrong input shape. Image should have 3 channel')

            # get prediction
            #out = self.model.predict_segmentation(
            #    inp=I,
            #    out_fname="/tmp/out.png"
            #)
            out = self.model.predict(I)
            out = out.reshape((2048, 1600, 3)).argmax(axis=2)

            text_part = 255 * np.ones(out.shape, 'B')
            text_part[np.where(out==1)] = 0
            LOG.info('text: %d percent', 100 * (1 - np.count_nonzero(text_part) / np.prod(out.shape)))

            image_part = 255 * np.ones(out.shape, 'B')
            image_part[np.where(out==2)] = 0
            LOG.info('image: %d percent', 100 * (1 - np.count_nonzero(image_part) / np.prod(out.shape)))

            image_part = ocrolib.array2pil(image_part)
            text_part = ocrolib.array2pil(text_part)

            image_part = image_part.resize(page_image.size, Image.BICUBIC)
            text_part = text_part.resize(page_image.size, Image.BICUBIC)

        else:
            I = ocrolib.pil2array(page_image)

            if len(I.shape) > 2:
                I = np.mean(I, 2)
            I = 1-I/I.max()
            rows, cols = I.shape

            # Generate Mask and Seed Images
            Imask, Iseed = self.pixMorphSequence_mask_seed_fill_holes(I)

            # Iseedfill: Union of Mask and Seed Images
            Iseedfill = self.pixSeedfillBinary(Imask, Iseed)

            # Dilation of Iseedfill
            mask = np.ones((3, 3))
            Iseedfill = ndimage.binary_dilation(Iseedfill, mask)

            # Expansion of Iseedfill to become equal in size of I
            Iseedfill = self.expansion(Iseedfill, (rows, cols))

            # Write Text and Non-Text images
            image_part = np.array(255*(1-I*Iseedfill), dtype='B')
            text_part = np.array(255*(1-I*(1-Iseedfill)), dtype='B')
            LOG.info('text: %d percent', 100 * (1 - np.count_nonzero(text_part) / np.prod(I.shape)))
            LOG.info('image: %d percent', 100 * (1 - np.count_nonzero(image_part) / np.prod(I.shape)))

            image_part = ocrolib.array2pil(image_part)
            text_part = ocrolib.array2pil(text_part)

        file_id = make_file_id(input_file, self.output_file_grp)
        file_path = self.workspace.save_image_file(image_part,
                                   file_id+"_img",
                                   page_id=input_file.pageId,
                                   file_grp=self.output_file_grp,
            )
        page.add_AlternativeImage(AlternativeImageType(
            filename=file_path, comments=page_coords['features'] + ',non_text'))

        file_path = self.workspace.save_image_file(text_part,
                                   file_id+"_txt",
                                   page_id=input_file.pageId,
                                   file_grp=self.output_file_grp,
            )
        page.add_AlternativeImage(AlternativeImageType(
            filename=file_path, comments=page_coords['features'] + ',clipped'))

    def pixMorphSequence_mask_seed_fill_holes(self, I):
        Imask = self.reduction_T_1(I)
        Imask = self.reduction_T_1(Imask)
        Imask = ndimage.binary_fill_holes(Imask)
        Iseed = self.reduction_T_4(Imask)
        Iseed = self.reduction_T_3(Iseed)
        mask = np.array(np.ones((5, 5)), dtype=int)
        Iseed = ndimage.binary_opening(Iseed, mask)
        Iseed = self.expansion(Iseed, Imask.shape)
        return Imask, Iseed

    def pixSeedfillBinary(self, Imask, Iseed):
        Iseedfill = copy.deepcopy(Iseed)
        s = np.ones((3, 3))
        Ijmask, k = ndimage.label(Imask, s)
        Ijmask2 = Ijmask * Iseedfill
        A = list(np.unique(Ijmask2))
        A.remove(0)
        for i in range(0, len(A)):
            x, y = np.where(Ijmask == A[i])
            Iseedfill[x, y] = 1
        return Iseedfill

    def reduction_T_1(self, I):
        A = np.logical_or(I[0:-1:2, :], I[1::2, :])
        A = np.logical_or(A[:, 0:-1:2], A[:, 1::2])
        return A

    def reduction_T_2(self, I):
        A = np.logical_or(I[0:-1:2, :], I[1::2, :])
        A = np.logical_and(A[:, 0:-1:2], A[:, 1::2])
        B = np.logical_and(I[0:-1:2, :], I[1::2, :])
        B = np.logical_or(B[:, 0:-1:2], B[:, 1::2])
        C = np.logical_or(A, B)
        return C

    def reduction_T_3(self, I):
        A = np.logical_or(I[0:-1:2, :], I[1::2, :])
        A = np.logical_and(A[:, 0:-1:2], A[:, 1::2])
        B = np.logical_and(I[0:-1:2, :], I[1::2, :])
        B = np.logical_or(B[:, 0:-1:2], B[:, 1::2])
        C = np.logical_and(A, B)
        return C

    def reduction_T_4(self, I):
        A = np.logical_and(I[0:-1:2, :], I[1::2, :])
        A = np.logical_and(A[:, 0:-1:2], A[:, 1::2])
        return A

    def expansion(self, I, rows_cols):
        r, c = I.shape
        rows, cols = rows_cols
        A = np.zeros((rows, cols))
        A[0:4*r:4, 0:4*c:4] = I
        A[1:4*r:4, :] = A[0:4*r:4, :]
        A[2:4*r:4, :] = A[0:4*r:4, :]
        A[3:4*r:4, :] = A[0:4*r:4, :]
        A[:, 1:4*c:4] = A[:, 0:4*c:4]
        A[:, 2:4*c:4] = A[:, 0:4*c:4]
        A[:, 3:4*c:4] = A[:, 0:4*c:4]
        return A

    def alpha_shape(self, coords, alpha):
        import shapely.geometry as geometry
        from shapely.ops import cascaded_union, polygonize
        from scipy.spatial import Delaunay
        """
        Compute the alpha shape (concave hull) of a set
        of points.
        @param points: Iterable container of points.
        @param alpha: alpha value to influence the
            gooeyness of the border. Smaller numbers
            don't fall inward as much as larger numbers.
            Too large, and you lose everything!
        """
#         if len(points) < 4:
#             # When you have a triangle, there is no sense
#             # in computing an alpha shape.
#             return geometry.MultiPoint(list(points))
#                    .convex_hull
        def add_edge(edges, edge_points, coords, i, j):
            """
            Add a line between the i-th and j-th points,
            if not in the list already
            """
            if (i, j) in edges or (j, i) in edges:
                # already added
                return
            edges.add( (i, j) )
            edge_points.append(coords[ [i, j] ])

        tri = Delaunay(coords)
        edges = set()
        edge_points = []
        # loop over triangles:
        # ia, ib, ic = indices of corner points of the
        # triangle
        for ia, ib, ic in tri.vertices:
            pa = coords[ia]
            pb = coords[ib]
            pc = coords[ic]
            # Lengths of sides of triangle
            a = math.sqrt((pa[0]-pb[0])**2 + (pa[1]-pb[1])**2)
            b = math.sqrt((pb[0]-pc[0])**2 + (pb[1]-pc[1])**2)
            c = math.sqrt((pc[0]-pa[0])**2 + (pc[1]-pa[1])**2)
            # Semiperimeter of triangle
            s = (a + b + c)/2.0
            # Area of triangle by Heron's formula
            area = math.sqrt(s*(s-a)*(s-b)*(s-c))
            circum_r = a*b*c/(4.0*area)
            # Here's the radius filter.
            #print circum_r
            if circum_r < 1.0/alpha:
                add_edge(edges, edge_points, coords, ia, ib)
                add_edge(edges, edge_points, coords, ib, ic)
                add_edge(edges, edge_points, coords, ic, ia)
        m = geometry.MultiLineString(edge_points)
        triangles = list(polygonize(m))
        return cascaded_union(triangles), edge_points

@click.command()
@ocrd_cli_options
def cli(*args, **kwargs):
    return ocrd_cli_wrap_processor(OcrdAnybaseocrTiseg, *args, **kwargs)
