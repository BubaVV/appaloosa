
from collections import defaultdict
from math import pi, degrees, radians, atan2, sqrt, log, acos
from random import (uniform,
                    sample,
                   )
from string import (ascii_lowercase,
                    ascii_letters,
                    digits,
                   )
from itertools import tee, product, combinations_with_replacement
import numpy as np
from scipy import ndimage as ndi
from scipy.misc import imread
from scipy.signal import find_peaks_cwt
from scipy.spatial.distance import euclidean, pdist
from scipy.ndimage.interpolation import rotate
from scipy.ndimage.filters import median_filter, gaussian_filter1d
from scipy.stats import norm
from skimage import draw
from skimage.color import (rgb2gray,
                           label2rgb,
                           rgb2lab,
                           rgb2hsv,
                           rgb2xyz,
                           rgb2luv,
                          )
from skimage.measure import label, regionprops
from skimage.segmentation import find_boundaries
from skimage.morphology import (watershed,
                                reconstruction,
                                erosion,
                                disk,
                                rectangle,
                                opening,
                                skeletonize,
                                binary_opening,
                                binary_closing,
                                binary_dilation,
                                binary_erosion,
                               )
from skimage.transform import probabilistic_hough_line, rescale
from skimage.feature import (peak_local_max,
                             hessian_matrix,
                             blob_log,
                            )
from skimage.filters import (threshold_otsu,
                             gaussian,
                             sobel,
                             threshold_local,
                             median,
                            )
from skimage.util import invert
from sklearn.cluster import KMeans
from sklearn.neighbors import NearestNeighbors
import matplotlib.pyplot as plt
import shapely
from shapely import geometry

#Uncomment only if using functions containing iplot
#from plotly.offline import (download_plotlyjs,
#                            init_notebook_mode,
#                            iplot,
#                           )
#from plotly import graph_objs
#init_notebook_mode()


def epoch_to_hash(epoch):
    """
    Generate an alphanumeric hash from a Unix epoch. Unix epoch is
    rounded to the nearest second before hashing.
    Arguments:
        epoch: Unix epoch time. Must be positive.
    Returns:
        Alphanumeric hash of the Unix epoch time.
    Cribbed from Scott W Harden's website
    http://www.swharden.com/blog/2014-04-19-epoch-timestamp-hashing/
    """
    if epoch <= 0:
        raise ValueError("epoch must be positive.")
    epoch = round(epoch)
    hashchars = digits + ascii_letters
    #hashchars = '01' #for binary
    epoch_hash = ''
    while epoch > 0:
        epoch_hash = hashchars[int(epoch % len(hashchars))] + epoch_hash
        epoch = int(epoch / len(hashchars))
    return epoch_hash


class Plate(object):
    def __init__(self,
                 image,
                 tag_in='original_image',
                 source_filename=None,
                ):
        self.image_stash = {tag_in: image.copy()}
        self.feature_stash = {}
        self.metadata = {'source_filename': source_filename}


    def crop_to_plate(self,
                      tag_in,
                      tag_out,
                      feature_out='crop_rotation',
                      second_pass=True,
                     ):
        image = self.image_stash[tag_in]
        g_img = rgb2gray(image)
        t_img = (g_img > threshold_otsu(g_img)).astype(np.uint8)
        labels, num_labels = (ndi
                              .measurements
                              .label(ndi.binary_fill_holes(t_img))
                             )
        objects = ndi.measurements.find_objects(labels)
        largest_object = max(objects, key=lambda x:image[x].size)
        rp = regionprops(t_img,
                         intensity_image=t_img,
                         coordinates='xy',
                        )
        assert len(rp) == 1
        rads = rp[0].orientation
        rads %= 2 * pi
        rotation = 90 - degrees(rads)
        r_img = rotate(image[largest_object],
                       angle=rotation,
                       axes=(1, 0),
                       reshape=True,
                       output=None,
                       order=5,
                       mode='constant',
                       cval=0.0,
                       prefilter=True,
                      )
        if second_pass:
            gr_img = rgb2gray(r_img)
            tr_img = (gr_img > threshold_otsu(gr_img)).astype(np.uint8)
            labels, num_labels = (ndi
                                  .measurements
                                  .label(ndi.binary_fill_holes(tr_img))
                                 )
            objects = ndi.measurements.find_objects(labels)
            largest_object = max(objects, key=lambda x:r_img[x].size)
            r_img = r_img[largest_object]
        self.image_stash[tag_out] = r_img
        self.feature_stash[feature_out] = rotation
        return self.image_stash[tag_out], self.feature_stash[feature_out]

    def crop_border(self,
                    tag_in,
                    tag_out='cropped_image',
                    border=30,
                   ):
        if border <= 0:
            raise ValueError("border must be > 0")
        if min(self.image_stash[tag_in].shape[:2]) < 2 * border + 1:
            raise ValueError("Cannot crop to image with 0 pixels.")
        cropped_image = self.image_stash[tag_in][border:-border,border:-border]
        self.image_stash[tag_out] = cropped_image
        return self.image_stash[tag_out], None

    @staticmethod
    def extend_line(line, image):
        #In image space x is width, y is height
        #(w1, h1), (w2, h2) = (x1, y1), (x2, y2)
        (w1, h1), (w2, h2) = line
        image_height, image_width = image.shape[:2]
        ihm, iwm = image_height - 1, image_width - 1
        if h1 == h2:
            left_width = 0
            left_height = h1
            right_width = iwm
            right_height = h1
            extended_line = ((left_width, left_height),
                             (right_width, right_height))
        elif w1 == w2:
            left_width = w1
            left_height = 0
            right_width = w1
            right_height = ihm
            extended_line = ((left_width, left_height),
                             (right_width, right_height))
        else:
            slope_h = (w2 - w1) / (h2 - h1)
            slope_w = (h2 - h1) / (w2 - w1)
            top_border_intersection = (0, w1 - slope_h * h1)
            right_border_intersection = (h1 + slope_w * (iwm - w1), iwm)
            bottom_border_intersection = (ihm, w1 + slope_h * (ihm - h1))
            left_border_intersection = (h1 - slope_w * w1, 0)
            border_intersections = (top_border_intersection,
                                    right_border_intersection,
                                    bottom_border_intersection,
                                    left_border_intersection,
                                   )
            valid_borders = []
            for BH, BW in border_intersections:
                if 0 <= BH <= ihm and 0 <= BW <= iwm:
                    valid_borders.append(True)
                else:
                    valid_borders.append(False)
            bounding_points = []
            for i, intersection in enumerate(border_intersections):
                if valid_borders[i]:
                    bounding_points.append(intersection)
            assert len(bounding_points) > 1
            bounding_points = bounding_points[:2]
            bounding_points = sorted(bounding_points, key=lambda x:x[0])
            ((left_height, left_width),
             (right_height, right_width)) = bounding_points
            extended_line = ((left_width, left_height),
                             (right_width, right_height))
        return extended_line

    def baseline_orient(self,
                        tag_in,
                        tag_out='baseline_oriented_image',
                        baseline_feature='baseline',
                        feature_out='reoriented_baseline',
                       ):
        baseline = self.feature_stash[baseline_feature]
        (x1, y1), (x2, y2) = baseline
        image_height = self.image_stash[tag_in]
        if min(y1, y2) < abs(max(y1, y2) - image_height):
            reoriented_image = np.fliplr(np.flipud(self.image_stash[tag_in]))
            self.image_stash[tag_out] = reoriented_image
            reoriented_baseline = ((x1, image_height - y2),
                                   (x2, image_height - y1))
            self.feature_stash[feature_out] = reoriented_baseline
        else:
            #No need to reorient
            self.image_stash[tag_out] = self.image_stash[tag_in].copy()
            self.feature_stash[feature_out] = baseline
        return self.image_stash[tag_out], self.feature_stash[feature_out]

    def baseline_mean(self,
                      baseline_feature='baseline',
                     ):
        baseline = self.feature_stash[baseline_feature]
        (w1, h1), (w2, h2) = (x1, y1), (x2, y2) = baseline
        mean_h, mean_w = np.mean((h1, h2)), np.mean((w1, w2))
        return mean_h, mean_w

    def display(self,
                tag_in,
                figsize=20,
                basins_feature=None,
                basin_alpha=0.1,
                baseline_feature=None,
                solvent_front_feature=None,
                lanes_feature=None,
                basin_centroids_feature=None,
                basin_lane_assignments_feature=None,
                basin_intensities_feature=None,
                basin_rfs_feature=None,
                lines_feature=None,
                draw_boundaries=True,
                side_by_side=False,
                display_labels=False,
                text_color='black',
                fontsize='20',
                blobs_feature=None,
                output_filename=None,
               ):
        image_shown = self.image_stash[tag_in]
        image_height, image_width = image_shown.shape[0], image_shown.shape[1]
        fig, ax = plt.subplots(ncols=1, nrows=1, figsize=(figsize, figsize))
        basins = (None if basins_feature is None
                  else self.feature_stash[basins_feature])
        if basins is None:
            ax.imshow(image_shown)
        else:
            g_img = rgb2gray(image_shown)
            if draw_boundaries:
                boundaries = find_boundaries(basins, mode='inner')
                bg_img = g_img * ~boundaries
            else:
                bg_img = g_img
            ax.imshow(label2rgb(basins, image=bg_img, alpha=basin_alpha))
        baseline = (None if baseline_feature is None
                    else self.feature_stash[baseline_feature])
        if baseline is not None:
            (w1, h1), (w2, h2) = (x1, y1), (x2, y2) = baseline
            ax.plot((w1, w2),
                    (h1, h2),
                    color='orange',
                    linestyle='-',
                    linewidth=1,
                   )
        lines = (None if lines_feature is None
                 else self.feature_stash[lines_feature])
        if lines is not None:
            for line in lines:
                (w1, h1), (w2, h2) = (x1, y1), (x2, y2) = line
                ax.plot((w1, w2),
                        (h1, h2),
                        color='yellow',
                        linestyle='-',
                        linewidth=1,
                        )
        solvent_front = (None if solvent_front_feature is None
                         else self.feature_stash[solvent_front_feature])
        if solvent_front is not None:
            (w1, h1), (w2, h2) = (x1, y1), (x2, y2) = solvent_front
            ax.plot((w1, w2),
                    (h1, h2),
                    color='purple',
                    linestyle='-',
                    linewidth=1,
                   )
        lanes = (None if lanes_feature is None
                 else self.feature_stash[lanes_feature])
        if lanes is not None:
            for lane in lanes:
                draw_h = (0, image_height)
                draw_w = (lane, lane)
                ax.plot(draw_w,
                        draw_h,
                        color='green',
                        linestyle='-',
                        linewidth=1,
                       )
        basin_centroids = (None if basin_centroids_feature is None
                           else self.feature_stash[basin_centroids_feature])
        basin_lane_assignments = (
                      None if basin_lane_assignments_feature is None
                      else self.feature_stash[basin_lane_assignments_feature]
                                 )
        basin_intensities = (
                           None if basin_intensities_feature is None
                           else self.feature_stash[basin_intensities_feature]
                            )
        basin_rfs = (None if basin_rfs_feature is None
                     else self.feature_stash[basin_rfs_feature])
        if basin_centroids is not None:
            for Label, centroid in basin_centroids.items():
                x, y = centroid
                if display_labels:
                    display_text = str(Label) + "; "
                else:
                    display_text = ''
                if basin_lane_assignments is not None:
                    display_text += ("row " +
                                     str(basin_lane_assignments[Label]))
                if basin_intensities is not None:
                    display_text += ("; I = " +
                                     str(basin_intensities[Label]))
                if basin_rfs is not None and Label in basin_rfs:
                    display_text += ("; rf = " +
                                     str(round(basin_rfs[Label], 2)))
                plt.text(y, x,
                         display_text,
                         color=text_color,
                         fontsize=fontsize,
                        )
        if blobs_feature is not None:
            blobs = self.feature_stash[blobs_feature]
            for blob in blobs:
                y, x, r = blob
                c = plt.Circle((x, y),
                               r,
                               color='red',
                               linewidth=2,
                               fill=False,
                              )
                ax.add_patch(c)
        if output_filename is None:
            plt.show()
        else:
            plt.savefig(output_filename)
            plt.close(fig)
        if side_by_side:
            #Currently, this is not really side-by-side, but below.
            fig, ax = plt.subplots(ncols=1, nrows=1,
                                   figsize=(figsize, figsize))
            ax.imshow(image_shown)
            if baseline is not None:
                (w1, h1), (w2, h2) = (x1, y1), (x2, y2) = baseline
                ax.plot((w1, w2),
                        (h1, h2),
                        color='orange',
                        linestyle='-',
                        linewidth=1,
                       )
            if lanes is not None:
                for lane in lanes:
                    draw_h = (0, image_height)
                    draw_w = (lane, lane)
                    ax.plot(draw_w,
                            draw_h,
                            color='green',
                            linestyle='-',
                            linewidth=1,
                           )
            if solvent_front is not None:
                (w1, h1), (w2, h2) = (x1, y1), (x2, y2) = solvent_front
                ax.plot((w1, w2),
                        (h1, h2),
                        color='purple',
                        linestyle='-',
                        linewidth=1,
                       )
            if output_filename is None:
                plt.show()
            else:
                plt.savefig(output_filename)
                plt.close(fig)

    @staticmethod
    def get_baseline_H_domain(baseline,
                              baseline_radius,
                             ):
        (LW, LH), (RW, RH) = baseline
        min_H, max_H = min(LH, RH), max(LH, RH)
        lower_H = max(0, min_H - baseline_radius)
        upper_H = max_H + baseline_radius + 1
        return lower_H, upper_H

    @staticmethod
    def rp_intensity(rp,
                     background,
                     background_basins=None,
                     radius=None,
                     radius_factor=None,
                     negative=False,
                     multiplier=1,
                    ):
        min_row, min_col, max_row, max_col = rp.bbox
        if radius is None:
            radius = int(np.ceil((sqrt(2) - 1) *
                                 max(abs(max_row - min_row),
                                     abs(max_col - min_col))))
        if radius_factor is not None:
            radius *= radius_factor
            radius = int(np.ceil(radius))
        subimage_minh = max(0, min_row - radius)
        subimage_maxh = max_row + radius
        subimage_minw = max(0, min_col - radius)
        subimage_maxw = max_col + radius
        subimage = background[subimage_minh:subimage_maxh,
                              subimage_minw:subimage_maxw]
        if background_basins is None:
            median_correction = np.median(subimage)
        else:
            subimage_basins =  background_basins[subimage_minh:subimage_maxh,
                                                 subimage_minw:subimage_maxw]
            filtered_subimage = subimage[np.where(subimage_basins == 0)]
            if len(filtered_subimage) == 0:
                median_correction = np.median(subimage)
            else:
                median_correction = np.median(filtered_subimage)
        intensity = (rp.mean_intensity - median_correction) * rp.area
        if negative:
            intensity *= -1
        intensity *= multiplier
        return intensity

    @staticmethod
    def pairwise(iterable):
        """
        Produces an iterable that yields "s -> (s0, s1), (s1, s2), (s2, s3)..."
        From Python itertools recipies.

        e.g.

        a = pairwise([5, 7, 11, 4, 5])
        for v, w in a:
            print [v, w]

        will produce

        [5, 7]
        [7, 11]
        [11, 4]
        [4, 5]

        The name of this function reminds me of Pennywise.
        """
        a, b = tee(iterable)
        next(b, None)
        return zip(a, b)

    def find_basin_centroids(self,
                             tag_in,
                             basins_feature='basins',
                             feature_out='basin_centroids',
                            ):
        intensity_image = rgb2gray(self.image_stash[tag_in])
        basins = self.feature_stash[basins_feature]
        RP = regionprops(label_image=basins,
                         intensity_image=intensity_image,
                         coordinates='xy',
                        )
        basin_centroids = {rp.label: rp.centroid for rp in RP}
        self.feature_stash[feature_out] = basin_centroids
        return None, self.feature_stash[feature_out]

    def measure_basin_intensities(self,
                                  tag_in,
                                  median_radius=None,
                                  filter_basins=False,
                                  radius_factor=None,
                                  basins_feature='basins',
                                  feature_out='basin_intensities',
                                  multiplier=1,
                                 ):
        g_img = rgb2gray(self.image_stash[tag_in])
        if median_radius is not None:
            mg_img = median(g_img, selem=disk(median_radius))
        else:
            mg_img = g_img
        basins = self.feature_stash[basins_feature]
        RP = regionprops(label_image=basins,
                         intensity_image=g_img,
                         coordinates='xy',
                        )
        if filter_basins:
            background_basins = basins
        else:
            background_basins = None
        basin_intensities = {rp.label:
                             int(round(Plate.rp_intensity(
                                           rp=rp,
                                           background=mg_img,
                                           background_basins=background_basins,
                                           radius=None,
                                           radius_factor=radius_factor,
                                           negative=True,
                                           multiplier=multiplier,
                                                         )
                                      )
                                )
                             for rp in RP}
        #TODO: Subtract notch intensities from blobs near baseline.
        self.feature_stash[feature_out] = basin_intensities
        return None, self.feature_stash[feature_out]

    @staticmethod
    def translate_line(line,
                       h, w,
                       extend=True,
                       image=None,
                      ):
        (w1, h1), (w2, h2) = line
        translated_line = (w1 + w, h1 + h), (w2 + w, h2 + h)
        if extend:
            if image is None:
                raise ValueError("If extending, need image.")
            translated_line = Plate.extend_line(line=translated_line,
                                                image=image,
                                               )
        return translated_line

    def compute_basin_rfs(self,
                          basin_centroids_feature='basin_centroids',
                          baseline_feature='baseline',
                          solvent_front_feature='solvent_front',
                          feature_out='basin_rfs',
                         ):
        basin_centroids = self.feature_stash[basin_centroids_feature]
        baseline = self.feature_stash[baseline_feature]
        solvent_front = self.feature_stash[solvent_front_feature]
        basin_rfs = {}
        for Label, centroid in basin_centroids.items():
            distance_to_base = Plate.point_line_distance(point=centroid[::-1],
                                                         line=baseline,
                                                        )
            distance_to_front = Plate.point_line_distance(point=centroid[::-1],
                                                          line=solvent_front,
                                                         )
            base_P1, base_P2 = baseline
            front_P1, front_P2 = solvent_front
            cb_1, cb_2 = (centroid[::-1], base_P1), (centroid[::-1], base_P2)
            cf_1, cf_2 = (centroid[::-1], front_P1), (centroid[::-1], front_P2)
            intersects_front_1 = Plate.line_segments_intersect(
                                                       segment_A=cb_1,
                                                       segment_B=solvent_front,
                                                              )
            intersects_front_2 = Plate.line_segments_intersect(
                                                       segment_A=cb_2,
                                                       segment_B=solvent_front,
                                                              )
            intersects_front = intersects_front_1 or intersects_front_2
            intersects_base_1 = Plate.line_segments_intersect(
                                                            segment_A=cf_1,
                                                            segment_B=baseline,
                                                             )
            intersects_base_2 = Plate.line_segments_intersect(
                                                            segment_A=cf_2,
                                                            segment_B=baseline,
                                                             )
            intersects_base = intersects_base_1 or intersects_base_2
            assert not (intersects_front and intersects_base)
            if intersects_front:
                denominator = distance_to_base - distance_to_front
                assert denominator > 0, (distance_to_base,
                                         distance_to_front,
                                         centroid,
                                         'intersects_front',
                                        )
                rf = distance_to_base / denominator
            elif intersects_base:
                denominator = distance_to_front - distance_to_base
                assert denominator > 0, (distance_to_base,
                                         distance_to_front,
                                         centroid,
                                         'intersects_base',
                                        )
                rf = -distance_to_base / denominator
            else:
                denominator = distance_to_front + distance_to_base
                assert denominator > 0, (distance_to_base,
                                         distance_to_front,
                                         centroid,
                                         'neither front nor base',
                                        )
                rf = distance_to_base / denominator
            basin_rfs[Label] = rf
        #baseline_mean = self.baseline_mean(baseline_feature=baseline_feature)
        #if solvent_front == 0 or solvent_front == baseline_mean:
        #    basin_rfs = None
        #else:
        #    basin_rfs = {}
        #    for Label, centroid in basin_centroids.iteritems():
        #        x, y = centroid
        #        if baseline_mean != solvent_front:
        #            rf = ((baseline_mean - x) /
        #                  (baseline_mean - solvent_front))
        #        else:
        #            rf = 'NaN'
        #        basin_rfs[Label] = rf
        self.feature_stash[feature_out] = basin_rfs
        return None, self.feature_stash[feature_out]

    @staticmethod
    def median_correct_image(image,
                             median_disk_radius,
                            ):
        g_img = rgb2gray(image)
        if median_disk_radius is None or median_disk_radius == 0:
            mg_img = g_img.copy()
        else:
            m_img = median(g_img, selem=disk(median_disk_radius))
            mg_img = g_img * np.mean(m_img) / m_img
        return mg_img

    @staticmethod
    def make_bT_bF(image, dtype=np.bool):
        bT = np.ones_like(image, dtype=dtype)
        bF = np.zeros_like(image, dtype=dtype)
        return bT, bF

    @staticmethod
    def open_close_boolean_basins(boolean_basins,
                                  open_close_size=10,
                                 ):
        open_close_disk = disk(open_close_size)
        opened = binary_opening(boolean_basins, selem=open_close_disk)
        closed_opened = binary_closing(opened, selem=open_close_disk)
        return closed_opened

    @staticmethod
    def open_close_label_basins(basins,
                                open_close_size=10,
                                exclude_label=None,
                                exclude_labels=None,
                               ):
        """Excluded labels are set to 0."""
        if exclude_labels is not None:
            exclude_labels = set(exclude_labels)
        else:
            exclude_labels = set()
        if exclude_label is not None:
            exclude_labels.add(exclude_label)
        open_closed_basins = np.zeros_like(basins)
        bT, bF = Plate.make_bT_bF(image=basins, dtype=np.bool)
        for L in np.unique(basins):
            if L in exclude_labels:
                continue
            label_boolean = np.where(basins == L, bT, bF)
            open_closed = Plate.open_close_boolean_basins(
                                               boolean_basins=label_boolean,
                                               open_close_size=open_close_size,
                                                         )
            open_closed_basins = np.where(open_closed, L, open_closed_basins)
        open_closed_basins = label(open_closed_basins)
        return open_closed_basins

    @staticmethod
    def most_frequent_label(basins,
                            image=None,
                           ):
        label_counts = np.bincount(basins.reshape(-1))
        most_frequent_label = np.argmax(label_counts)
        background_pixel_coordinates = np.where(basins == most_frequent_label)
        if image is not None:
            background_pixel_values = image[background_pixel_coordinates]
        else:
            background_pixel_values = None
        return (most_frequent_label,
                background_pixel_coordinates,
                background_pixel_values,
               )

    def remove_most_frequent_label(self,
                                   basins_feature='basins',
                                   feature_out='filtered_basins',
                                   debug_output=False,
                                  ):
        basins = self.feature_stash[basins_feature]
        (most_frequent_label,
         background_pixel_coordinates,
         background_pixel_values,
        ) = Plate.most_frequent_label(basins=basins)
        empty_basin_template = np.zeros_like(basins)
        filtered_basins = np.where(basins != most_frequent_label,
                                   basins,
                                   empty_basin_template,
                                  )
        filtered_basins = label(filtered_basins)
        #if debug_output:
        #    print("filtered basins debug")
        #    light_dummy = np.ones_like(basins) * np.iinfo(basins.dtype).max
        #    self.image_stash['debug_display'] = light_dummy
        #    self.feature_stash['debug_basins'] = filtered_basins
        #    self.display(tag_in='debug_display',
        #                 basins_feature='debug_basins',
        #                 figsize=10,
        #                 display_labels=True,
        #                )
        self.feature_stash[feature_out] = filtered_basins
        return None, self.feature_stash[feature_out]

    def waterfall_segmentation(self,
                               tag_in,
                               feature_out='waterfall_basins',
                               R_out='R_img',
                               mg_out='mg_img',
                               median_disk_radius=31,
                               smoothing_sigma=0,
                               threshold_opening_size=3,
                               basin_open_close_size=10,
                               skeleton_label=0,
                               debug_output=False,
                              ):
        """
        Algorithm based on

        Beucher, Serge. "Watershed, hierarchical segmentation and waterfall
        algorithm." Mathematical morphology and its applications to image
        processing. Springer Netherlands, 1994. 69-76.
        DOI 10.1007/978-94-011-1040-2_10
        """
        working_image = self.image_stash[tag_in]
        if debug_output:
            print("waterfall input image debug")
            self.image_stash['debug_display'] = working_image
            self.display(tag_in='debug_display',
                         figsize=10,
                        )
        o_img = working_image
        g_img = rgb2gray(o_img)
        if smoothing_sigma > 0:
            g_img = gaussian(g_img, sigma=smoothing_sigma)
        if debug_output:
            print("smoothing image debug")
            self.image_stash['debug_display'] = g_img
            self.display(tag_in='debug_display',
                         figsize=10,
                        )
        if median_disk_radius is None:
            median_disk_radius = (max(g_img.shape) // 2) * 2 + 1
            mg_img = g_img.copy()
        else:
            mg_img = \
              Plate.median_correct_image(image=g_img,
                                         median_disk_radius=median_disk_radius)
        self.image_stash[mg_out] = mg_img.copy()
        if debug_output:
            print("median debug")
            self.image_stash['debug_display'] = mg_img
            self.display(tag_in='debug_display',
                         figsize=10,
                        )
        #find maxima at high resolution
        n_img = np.amax(mg_img) - mg_img
        maxima_distance = 5 #using 'thick' boundaries below,
                            #so this needs to be sane
        local_maxima = peak_local_max(n_img, indices=False,
                                      min_distance=maxima_distance)
        markers = label(local_maxima)
        #perform watershed
        W_labels = watershed(mg_img, markers=markers)
        #find boundaries, which is the actual W
        W = find_boundaries(W_labels, connectivity=1, mode='thick')
        mg_max = np.amax(mg_img)
        mg_max_array = np.ones_like(mg_img)
        mg_max_array *= mg_max
        g = np.where(W, mg_img, mg_max_array)
        if debug_output:
            print("g debug")
            self.image_stash['debug_display'] = g
            self.display(tag_in='debug_display',
                         figsize=10,
                        )
        #reconstruction by erosion
        R = reconstruction(g, mg_img, method='erosion')
        self.image_stash[R_out] = R.copy()
        if debug_output:
            print("R debug")
            self.image_stash['debug_display'] = R
            self.display(tag_in='debug_display',
                         figsize=10,
                        )
        #perform watershed on R
        n_R = np.amax(R) - R
        #thresh = threshold_li(n_R)
        #thresh = threshold_otsu(n_R)
        thresh = threshold_local(n_R, median_disk_radius)
        thresh_image = n_R > thresh
        thresh_image = opening(image=thresh_image,
                               selem=disk(threshold_opening_size))
        if debug_output:
            print("thresh_image debug")
            self.image_stash['debug_display'] = thresh_image
            self.display(tag_in='debug_display',
                         figsize=10,
                        )
        local_maxi = thresh_image
        #so that local_maxi and skel don't overlap
        local_maxi_compliment = erosion(~local_maxi, disk(2))
        skel = skeletonize(local_maxi_compliment)
        skel = np.logical_xor(skel, np.logical_and(skel, local_maxi))
        local_maxi = np.logical_or(local_maxi, skel)
        markers = label(local_maxi)
        if debug_output:
            print("local_maxi markers debug")
            self.image_stash['debug_display'] = g_img
            self.feature_stash['debug_basins'] = markers
            self.display(tag_in='debug_display',
                         basins_feature='debug_basins',
                         figsize=10,
                         display_labels=True,
                        )
        WR_labels = watershed(R, markers=markers)
        if skeleton_label is not None:
            superlabel = np.amax(WR_labels) + 1
            select_skeleton = np.where(skel,
                                       WR_labels,
                                       np.ones_like(skel) * superlabel,
                                      )
            skeleton_labels = np.unique(select_skeleton)
            skeleton_bincount = np.bincount(select_skeleton.reshape(-1))
            skeleton_label = np.argmax(skeleton_bincount[:-1])
            WR_labels = np.where(WR_labels != skeleton_label,
                                 WR_labels,
                                 np.zeros_like(WR_labels),
                                )
            WR_labels = label(WR_labels)
        if debug_output:
            print("first round WR_labels debug")
            self.image_stash['debug_display'] = g_img
            self.feature_stash['debug_basins'] = WR_labels
            self.display(tag_in='debug_display',
                         basins_feature='debug_basins',
                         figsize=10,
                         display_labels=True,
                        )
            WR_unique = tuple(np.unique(WR_labels))
            smallest_WR_label = min(WR_unique)
            largest_WR_label = max(WR_unique)
            print(("WR_labels: " + str(smallest_WR_label) + " through "
                  + str(largest_WR_label)))
        if debug_output:
            pixel_values = R.flatten().tolist()
            plot_target = pixel_values
            obn = 1000
            print(("obn = " + str(obn)))
            hist, bins = np.histogram(a=plot_target, bins=obn)
            traces = [graph_objs.Scatter(x=bins, y=hist)]
            layout = graph_objs.Layout(plot_bgcolor='rgba(0,0,0,0)',
                                       paper_bgcolor='rgba(0,0,0,0)',
                                       yaxis=dict(title='Count'),
                                       xaxis=dict(title='Pixel value'))
            fig = graph_objs.Figure(data=traces, layout=layout)
            iplot(fig)
        if basin_open_close_size is not None:
            (most_frequent_label,
             background_pixel_coordinates,
             background_pixel_values,
            ) = Plate.most_frequent_label(basins=WR_labels)
            open_closed_basins = Plate.open_close_label_basins(
                                         basins=WR_labels,
                                         open_close_size=basin_open_close_size,
                                         exclude_label=most_frequent_label,
                                                              )
            WR_labels = label(open_closed_basins)
        if debug_output:
            print("openclosed WR_labels debug")
            self.image_stash['debug_display'] = g_img
            self.feature_stash['debug_basins'] = WR_labels
            self.display(tag_in='debug_display',
                         basins_feature='debug_basins',
                         figsize=10,
                         display_labels=True,
                        )
        self.feature_stash[feature_out] = WR_labels
        return None, self.feature_stash[feature_out]

    @staticmethod
    def overlay_labels(waterfall_labels,
                       watershed_labels,
                       debug_output=False,
                      ):
        if waterfall_labels.shape != watershed_labels.shape:
            raise ValueError((waterfall_labels.shape, watershed_labels.shape))
        label_mapper = {}
        label_counter = 1
        overlaid_labels = np.zeros_like(waterfall_labels)
        for (h, w), waterfall_L in np.ndenumerate(waterfall_labels):
            if waterfall_L == 0:
                continue
            watershed_L = watershed_labels[h, w]
            if watershed_L == 0:
                continue
            if (waterfall_L, watershed_L) not in label_mapper:
                label_mapper[(waterfall_L, watershed_L)] = label_counter
                label_counter += 1
            overlaid_labels[h, w] = label_mapper[(waterfall_L, watershed_L)]
        return overlaid_labels

    def overlay_watershed(self,
                          tag_in,
                          intensity_image_tag='intensity_image',
                          median_radius=None,
                          filter_basins=False,
                          waterfall_basins_feature='waterfall_basins',
                          feature_out='overlaid_watershed_basins',
                          min_localmax_dist=10,
                          smoothing_sigma=0,
                          min_area=10,
                          min_intensity=1,
                          rp_radius_factor=0.5,
                          basin_open_close_size=10,
                          debug_output=False,
                          multiplier=1,
                         ):
        g_img = rgb2gray(self.image_stash[tag_in])
        if smoothing_sigma > 0:
            g_img = gaussian(g_img, sigma=smoothing_sigma)
        ng_img = np.amax(g_img) - g_img
        local_maxi = peak_local_max(ng_img, indices=False,
                                    min_distance=min_localmax_dist)
        markers = label(local_maxi)
        WS_labels = watershed(g_img, markers=markers)
        if debug_output:
            print("watershed labels debug")
            self.image_stash['debug_display'] = g_img
            self.feature_stash['debug_basins'] = WS_labels
            self.display(tag_in='debug_display',
                         basins_feature='debug_basins',
                         figsize=10,
                         display_labels=True,
                        )
        WR_labels = self.feature_stash[waterfall_basins_feature]
        overlaid_labels = Plate.overlay_labels(waterfall_labels=WR_labels,
                                               watershed_labels=WS_labels,
                                               debug_output=debug_output,
                                              )
        if debug_output:
            print("overlaid labels debug")
            self.image_stash['debug_display'] = g_img
            self.feature_stash['debug_basins'] = overlaid_labels
            self.display(tag_in='debug_display',
                         basins_feature='debug_basins',
                         figsize=10,
                         display_labels=True,
                        )
        intensity_image = rgb2gray(self.image_stash[intensity_image_tag])
        RP = regionprops(overlaid_labels,
                         intensity_image=intensity_image,
                         coordinates='xy',
                        )
        if median_radius is not None:
            median_intensity_image = median(intensity_image,
                                            selem=disk(median_radius),
                                           )
        else:
            median_intensity_image = intensity_image
        delete_labels = set()
        #image_height, image_width = g_img.shape
        if filter_basins:
            background_basins = overlaid_labels
        else:
            background_basins = None
        for rp in RP:
            if min_area is not None and rp.area < min_area:
                delete_labels.add(rp.label)
            if min_intensity is not None:
                intensity = Plate.rp_intensity(
                                          rp=rp,
                                          background=median_intensity_image,
                                          background_basins=background_basins,
                                          radius=None,
                                          radius_factor=rp_radius_factor,
                                          #radius=max(image_height,
                                          #           image_width,
                                          #          ),
                                          negative=True,
                                          multiplier=multiplier,
                                              )
                if intensity < min_intensity:
                    if debug_output:
                        print(("intensity = " + str(intensity)))
                    delete_labels.add(rp.label)
        O, Z = Plate.make_bT_bF(image=overlaid_labels, dtype=np.int)
        for L in list(delete_labels):
            mask = np.where(overlaid_labels == L, Z, O)
            overlaid_labels = np.multiply(overlaid_labels, mask)
        overlaid_labels = overlaid_labels.astype(np.int)
        if debug_output:
            print("filtered overlaid labels debug")
            self.image_stash['debug_display'] = g_img
            self.feature_stash['debug_basins'] = overlaid_labels
            self.display(tag_in='debug_display',
                         basins_feature='debug_basins',
                         figsize=10,
                         display_labels=True,
                        )
        if basin_open_close_size is not None:
            (most_frequent_label,
             background_pixel_coordinates,
             background_pixel_values,
            ) = Plate.most_frequent_label(basins=overlaid_labels)
            open_closed_basins = Plate.open_close_label_basins(
                                         basins=overlaid_labels,
                                         open_close_size=basin_open_close_size,
                                         exclude_label=most_frequent_label,
                                                              )
            overlaid_labels = label(open_closed_basins)
            if debug_output:
                print("openclosed overlaid labels debug")
                self.image_stash['debug_display'] = g_img
                self.feature_stash['debug_basins'] = overlaid_labels
                self.display(tag_in='debug_display',
                             basins_feature='debug_basins',
                             figsize=10,
                             display_labels=True,
                            )
        self.feature_stash[feature_out] = overlaid_labels
        return None, self.feature_stash[feature_out]

    @staticmethod
    def line_segments_angle(segment_A, segment_B):
        (xA1, yA1), (xA2, yA2) = segment_A
        (xB1, yB1), (xB2, yB2) = segment_B
        vector_A = xA2 - xA1, yA2 - yA1
        vector_B = xB2 - xB1, yB2 - yB1
        AdotB = np.dot(vector_A, vector_B)
        Amag, Bmag = np.linalg.norm(vector_A), np.linalg.norm(vector_B)
        cos_angle = AdotB / (Amag * Bmag)
        angle = degrees(acos(cos_angle))
        #acute_angle = min(angle % 180, 180 - angle % 180)
        #return acute_angle
        return angle

    @staticmethod
    def standard_line_angle(line):
        (w1, h1), (w2, h2) = (x1, y1), (x2, y2) = line
        if h2 >= h1:
            standard_line_segment = ((h1, w1), (h2, w2))
        else:
            standard_line_segment = ((h2, w2), (h1, w1))
        standard_image_segment = ((0, 0), (0, 1))
        angle = Plate.line_segments_angle(segment_A=standard_line_segment,
                                          segment_B=standard_image_segment,
                                         )
        return angle

    @staticmethod
    def line_segments_intersect(segment_A,
                                segment_B,
                                error_tolerance=10**-5,
                               ):
        (xA1, yA1), (xA2, yA2) = segment_A
        (xB1, yB1), (xB2, yB2) = segment_B
        xA, yA = xA2 - xA1, yA2 - yA1
        xB, yB = xB2 - xB1, yB2 - yB1
        denominator = yB * xA - xB * yA
        if denominator == 0:
            #parallel segments
            line_distance = Plate.point_line_distance(point=(xA1, yA1),
                                                      line=segment_B)
            if line_distance < error_tolerance:
                intersect = True
            else:
                intersect = False
        else:
            numerator_A = xB * (yA1 - yB1) - yB * (xA1 - xB1)
            numerator_B = xA * (yA1 - yB1) - yA * (xA1 - xB1)
            uA, uB = numerator_A / denominator, numerator_B / denominator
            if 0 <= uA <= 1 and 0 <= uB <= 1:
                intersect = True
            else:
                intersect = False
        return intersect

    @staticmethod
    def point_line_distance(point, line):
        """
        point: (x, y)
        line: ((x1, y1), (x2, y2))

        distance = ||(a - p) - ((a - p).(a - b))(a - b) / ||a - b||^2 ||,
        where p = (x, y), a = (x1, y1), b = (x2, y2), and ||X|| is the
        Euclidean norm
        """
        p = point
        a, b = line
        p, a, b = np.array(p), np.array(a), np.array(b)
        u = (a - b) / np.linalg.norm(a - b)
        numerator_vector = (a - p) - np.dot((a - p), u) * u
        numerator_norm = np.linalg.norm(numerator_vector)
        return float(numerator_norm)

    def subdivide_basin(self,
                        tag_in,
                        feature_out,
                        basins_feature,
                        target_basin,
                        smoothing_sigma=None,
                        maxima_distance=5,
                       ):
        grayscale_image = self.image_stash[tag_in]
        basins = self.feature_stash[basins_feature]
        if smoothing_sigma is not None:
            grayscale_image = gaussian(grayscale_image, sigma=smoothing_sigma)
        n_img = np.amax(grayscale_image) - grayscale_image
        local_maxima = peak_local_max(n_img,
                                      indices=False,
                                      min_distance=maxima_distance,
                                     )
        local_maxima = np.where(basins == target_basin,
                                local_maxima,
                                False,
                               )
        markers = label(local_maxima)
        W_labels = watershed(grayscale_image,
                             markers=markers,
                            )
        largest_basins_tag = np.amax(basins)
        W_labels += largest_basins_tag + 1
        updated_labels = np.where(basins == target_basin,
                                  W_labels,
                                  basins,
                                 )
        basin_check = np.where(basins == W_labels,
                               True,
                               False,
                              )
        assert np.amax(basin_check) == False
        self.feature_stash[feature_out] = updated_labels

    def linear_split_basin(self,
                           feature_out,
                           basins_feature,
                           line,
                           target_basin,
                          ):
        (h1, w1), (h2, w2) = line
        basins = self.feature_stash[basins_feature]
        split_matrix = np.zeros_like(basins).astype(np.bool)
        for (h, w), basin in np.ndenumerate(basins):
            if basin != target_basin:
                continue
            elif w1 == w2:
                if w > w1:
                    split_matrix[h, w] = True
            elif h1 == h2:
                if h > h1:
                    split_matrix[h, w] = True
            else:
                slope = float(w2 - w1) / (h2 - h1)
                test_w = slope * (h - h1) + w1
                if test_w > w:
                    split_matrix[h, w] = True
        largest_basins_tag = np.amax(basins)
        new_tag = largest_basins_tag + 1
        largest_mask = np.where(basins == new_tag,
                                True,
                                False,
                               )
        assert np.amax(largest_mask) == False
        updated_basins = np.where(split_matrix,
                                  new_tag,
                                  basins,
                                 )
        self.feature_stash[feature_out] = updated_basins

    @staticmethod
    def points_colinear(points, error_tolerance=10**-5):
        points = sorted(points, key=lambda x:x[0])
        h_coordinates, w_coordinates = list(zip(*points))
        #Special cases: two ponits, vertical or horizontal line
        if len(points) == 2:
            colinear = True
        elif len(set(h_coordinates)) == 1 or len(set(w_coordinates)) == 1:
            colinear = True
        else:
            #This works because points sorted above and confirmed
            #not to be vertical or horizontal
            (a_h, a_w), (b_h, b_w) = points[0], points[-1]
            #Vertical slope special case taken care of above
            slope = float(b_h - a_h) / (b_w - a_w)
            expected_h_coordinates = [a_h + slope * (w - a_w)
                                      for (h, w) in points]
            errors = [abs(expected_h - h_coordinates[i])
                      for i, expected_h in enumerate(expected_h_coordinates)]
            if max(errors) > error_tolerance:
                colinear = False
            else:
                colinear = True
        return colinear

    @staticmethod
    def all_pairwise_distances(points):
        distances = {(p1, p2): np.linalg.norm(np.array(p1) - np.array(p2))
                     for p1, p2 in product(points, repeat=2)}
        return distances

    @staticmethod
    def find_largest_distance(points, method="naive"):
        if method == "naive":
            distances = Plate.all_pairwise_distances(points=points)
            largest_distance = max(distances.values())
        elif method == "convex_hull":
            raise NotImplementedError("For small number of points, 'naive' "
                                      "will do.")
            if Plate.points_colinear(points):
                #Special case: points are on the same line
                points = sorted(points, key=lambda x:np.linalg.norm(x))
                largest_distance = np.linalg.norm(points[-1] - points[0])
            else:
                hull = ConvexHull(points)
                #There is an O(n) algorithm that can use the hull to find
                #the most distant points
        else:
            raise ValueError("Undefined method.")
        return largest_distance

    @staticmethod
    def grid_hough(points):
        """
        points: [(h1, w1), (h2, w2), (h3, w3), ...]

        Returns optimal grid angle in degrees.
        """
        #Make all unit vectors representing all possible grid angles
        thetas = np.deg2rad(np.arange(0, 180))
        sin_cache, cos_cache = np.sin(thetas), np.cos(thetas)
        unit_vectors = list(zip(cos_cache, sin_cache))
        perpendicular_unit_vectors = [(unit_vectors[i], unit_vectors[i + 90])
                                      for i in range(90)]
        #Calculate largest distance between two points
        largest_distance = Plate.find_largest_distance(points=points,
                                                       method='naive')
        #Compute total distance metric for all grid angles
        distance_metrics = {}
        for g, grid_archetype in enumerate(perpendicular_unit_vectors):
            point_grid_archetypes = []
            for point in points:
                h, w = point
                point_grid_archetype = tuple([((h, w),
                                               (h + unit_vector_h,
                                                w + unit_vector_w))
                                              for unit_vector_h, unit_vector_w
                                              in grid_archetype])
                point_grid_archetypes.append(point_grid_archetype)
            total_distances = 0
            for p, point in enumerate(points):
                minimal_distance_to_grid = largest_distance
                for p2, grid_archetype in enumerate(point_grid_archetypes):
                    if p == p2:
                        #Avoid comparing point to its own grid archetype
                        continue
                    u1, u2 = grid_archetype
                    u1_distance = Plate.point_line_distance(point=point,
                                                            line=u1)
                    u2_distance = Plate.point_line_distance(point=point,
                                                            line=u2)
                    min_u_distance = min(u1_distance, u2_distance)
                    minimal_distance_to_grid = min(minimal_distance_to_grid,
                                                   min_u_distance)
                total_distances += minimal_distance_to_grid
            distance_metrics[g] = total_distances
        optimal_angle = min(distance_metrics, key=distance_metrics.get)
        return optimal_angle

    @staticmethod
    def generate_rotation_matrix(angle):
        """angle in degrees"""
        angle_radians = radians(angle)
        s, c = np.sin(angle_radians), np.cos(angle_radians)
        rotation_matrix = np.array([[c, -s],
                                    [s,  c]])
        return rotation_matrix

    @staticmethod
    def rotate_points(points, angle):
        """angle in degrees"""
        rotation_matrix = Plate.generate_rotation_matrix(angle=angle)
        rotated_points = [tuple(np.dot(rotation_matrix, np.array(point)))
                          for point in points]
        return tuple(rotated_points)

    @staticmethod
    def bounding_hypercube(points):
        X = list(zip(*points))
        minmax_pairs = tuple([(min(coordinates), max(coordinates))
                              for coordinates in X])
        return minmax_pairs

    @staticmethod
    def Wk(clustered_points):
        sums_of_pairwise_distances = {cluster: sum(pdist(points))
                                      for cluster, points
                                      in clustered_points.items()}
        cluster_sizes = {cluster: len(points)
                         for cluster, points in clustered_points.items()}
        return sum([Dr / (2.0 * cluster_sizes[cluster])
                    for cluster, Dr in sums_of_pairwise_distances.items()])

    @staticmethod
    def fit_predict_dict(kmeans_assignments,
                         points,
                        ):
        clustered_points = defaultdict(list)
        for cluster, point in zip(kmeans_assignments, points):
            clustered_points[cluster].append(point)
        return clustered_points

    @staticmethod
    def gap_statistic(clustered_points,
                      num_ref_datasets=10,
                     ):
        """
        clustered_points: {cluster_id: (point1, point2, ..., point_i)}

        ... where all points and cluster centers are represented as coordinate
        tuples.


        Gap statistic from

        Tibshirani, Robert, Guenther Walther, and Trevor Hastie. "Estimating
        the number of clusters in a data set via the gap statistic." Journal of
        the Royal Statistical Society: Series B (Statistical Methodology) 63.2
        (2001): 411-423. DOI: 10.1111/1467-9868.00293
        """
        data_Wk = Plate.Wk(clustered_points=clustered_points)
        all_points = sum(list(clustered_points.values()), [])
        minmax_pairs = Plate.bounding_hypercube(all_points)
        num_points = sum([len(points)
                          for cluster, points
                          in clustered_points.items()])
        ref_kmeans = KMeans(n_clusters=len(clustered_points))
        ref_log_Wks = []
        for d in range(num_ref_datasets):
            random_points = np.array([[uniform(L, U) for L, U in minmax_pairs]
                                      for r in range(num_points)])
            ref_assignments = ref_kmeans.fit_predict(random_points)
            ref_clustered_points = \
                     Plate.fit_predict_dict(kmeans_assignments=ref_assignments,
                                            points=random_points)
            ref_Wk = Plate.Wk(clustered_points=ref_clustered_points)
            ref_log_Wks.append(log(ref_Wk))
        ref_log_Wks_mean = np.mean(ref_log_Wks)
        ref_log_Wks_std = np.std(ref_log_Wks)
        gap_statistic = ref_log_Wks_mean - log(data_Wk)
        sk = sqrt(1 + 1.0 / num_ref_datasets) * ref_log_Wks_std
        return gap_statistic, sk

    @staticmethod
    def PhamDimovNguyen(clustered_points,
                        cluster_centers,
                        prior_S_k,
                        prior_a_k,
                       ):
        """
        clustered_points: {cluster_id: (point1, point2, ..., point_i)}
        cluter_centers: {cluster_id: cluster_center}


        Metric taken from

        Pham, Duc Truong, Stefan S. Dimov, and Chi D. Nguyen. "Selection of K
        in K-means clustering." Proceedings of the Institution of Mechanical
        Engineers, Part C: Journal of Mechanical Engineering Science 219.1
        (2005): 103-119. DOI: 10.1243/095440605X8298
        """
        num_dimensions = len(next(iter(clustered_points.values()))[0])
        if num_dimensions < 2:
            raise ValueError("Metric not defined in spaces with less than 2 "
                             "dimensions.")
        distortions = {cluster: sum([euclidean(center, point)**2
                                     for point in clustered_points[cluster]])
                       for cluster, center in cluster_centers.items()}
        S_k = sum(distortions.values())
        k = len(clustered_points)
        if k == 1:
            a_k = None
        elif k == 2:
            a_k = 1 - 3.0 / (4.0 * num_dimensions)
        elif k > 2:
            a_k = prior_a_k + (1 - prior_a_k) / 6.0
        if k == 1:
            f_k = 1
        elif prior_S_k == 0:
            f_k = 1
        elif prior_S_k != 0:
            f_k = S_k / float(a_k * prior_S_k)
        return f_k, S_k, a_k

    @staticmethod
    def determine_k(points,
                    max_k=None,
                    method='jenks',
                    **kwargs
                   ):
        if max_k is None:
            max_k = len(points)
        if method == 'jenks':
            #TODO: 1-cluster case
            gvf_threshold = kwargs.get('gvf_threshold', 0.9)
            gvfs = []
            all_points = sum(points.tolist(), [])
            all_points_mean = np.mean(all_points)
            for n_clusters in range(1, max_k + 1):
                kmeans = KMeans(n_clusters=n_clusters)
                assignments = kmeans.fit_predict(points)
                clustered_points = \
                         Plate.fit_predict_dict(kmeans_assignments=assignments,
                                                points=points)
                cluster_centers = \
                              dict(enumerate(kmeans.cluster_centers_.tolist()))
                #sum of squared deviations from cluster means
                sdcm = np.sum([euclidean(pts, cluster_centers[cluster])**2
                               for cluster, pts
                               in clustered_points.items()
                               for pt in pts])
                #sum of squared deviations from data mean
                sdam = np.sum([euclidean(pt, all_points_mean)**2
                               for cluster, pts
                               in clustered_points.items()
                               for pt in pts])
                gvf = (sdam - sdcm) / sdam
                gvfs.append(gvf)
                if gvf > gvf_threshold:
                    break
            optimal_k = len(gvfs)
        elif method == 'gap':
            num_ref_datasets = kwargs.get('num_ref_datasets', 100)
            gapstats = []
            for n_clusters in range(1, max_k + 1):
                kmeans = KMeans(n_clusters=n_clusters)
                assignments = kmeans.fit_predict(points)
                clustered_points = \
                         Plate.fit_predict_dict(kmeans_assignments=assignments,
                                                points=points)
                gap_stat, sk = Plate.gap_statistic(
                                             clustered_points=clustered_points,
                                             num_ref_datasets=num_ref_datasets,
                                                  )
                if not gapstats:
                    gapstats.append((gap_stat, sk))
                    continue
                prior_gap_stat, prior_sk = gapstats[-1]
                if prior_gap_stat < gap_stat - sk:
                    gapstats.append((gap_stat, sk))
                    continue
                else:
                    break
            optimal_k = len(gapstats)
        elif method == 'PDN':
            metrics = []
            for n_clusters in range(1, max_k + 1):
                kmeans = KMeans(n_clusters=n_clusters)
                assignments = kmeans.fit_predict(points)
                clustered_points = \
                         Plate.fit_predict_dict(kmeans_assignments=assignments,
                                                points=points)
                cluster_centers = \
                              dict(enumerate(kmeans.cluster_centers_.tolist()))
                if not metrics:
                    prior_S_k, prior_a_k = None, None
                else:
                    prior_f_k, prior_S_k, prior_a_k = metrics[-1]
                f_k, S_k, a_k = Plate.PhamDimovNguyen(
                                             clustered_points=clustered_points,
                                             cluster_centers=cluster_centers,
                                             prior_S_k=prior_S_k,
                                             prior_a_k=prior_a_k,
                                                     )
                metrics.append((f_k, S_k, a_k))
            f_ks = [f_k for f_k, S_k, a_k in metrics]
            optimal_k = np.argmin(f_ks)
        else:
            raise ValueError("Undefined method.")
        return optimal_k

    @staticmethod
    def map_sort(items,
                 reverse=False,
                 inverse=False,
                ):
        enumerated_items = tuple(enumerate(items))
        sorted_enumeration = sorted(enumerated_items,
                                    key=lambda x:x[1],
                                    reverse=reverse,
                                   )
        sort_mapping = {original_index: sorted_index
                        for sorted_index, (original_index, item)
                        in enumerate(sorted_enumeration)}
        if inverse:
            sort_mapping = {v: k for k, v in sort_mapping.items()}
        return sort_mapping

    @staticmethod
    def XYZ2xyY(image):
        X, Y, Z = image[..., 0], image[..., 1], image[..., 2]
        norm = X + Y + Z
        norm = np.where(norm == 0, 1, norm)
        x, y = X / norm, Y / norm
        return np.dstack((x, y, Y))

    def basin_colors(self,
                     tag_in,
                     basins_feature='basins',
                     feature_out='basin_colors',
                     color_space='lab',
                    ):
        rgb_image = self.image_stash[tag_in]
        if color_space == 'rgb':
            color_image = rgb_image
        elif color_space == 'lab':
            color_image = rgb2lab(rgb_image)
        elif color_space == 'hsv':
            color_image = rgb2hsv(rgb_image)
        elif color_space == 'XYZ':
            color_image = rgb2xyz(rgb_image)
        elif color_space == 'xyY':
            color_image = Plate.XYZ2xyY(rgb2xyz(rgb_image))
        elif color_space == 'luv':
            color_image = rgb2luv(rgb_image)
        else:
            raise ValueError("Invalid color space.")
        basins = self.feature_stash[basins_feature]
        basin_pixels = defaultdict(list)
        for (h, w), Label in np.ndenumerate(basins):
            pixel_color = tuple(color_image[h, w].tolist())
            basin_pixels[Label].append(pixel_color)
        basin_pixels = {basin: tuple(pixels)
                        for basin, pixels in basin_pixels.items()}
        self.feature_stash[feature_out] = (color_space, basin_pixels)
        return None, self.feature_stash[feature_out]

    @staticmethod
    def nn_cluster_distance(cluster_A,
                            cluster_B,
                            normalize=True,
                           ):
        """
        1. For each member of cluster_B, find the closest member of cluster_A.
        2. Compute the distance between them.
        3. Returns sum of all such distances.
        """
        nbrs = (NearestNeighbors(n_neighbors=1, n_jobs=-1)
                .fit(np.array(cluster_A))
               )
        distances, indices = nbrs.kneighbors(np.array(cluster_B))
        if normalize:
            cluster_distance = np.mean(distances)
        else:
            cluster_distance = np.sum(distances)
        return cluster_distance

    def mutual_color_distances(self,
                               basin_colors_feature='basin_colors',
                               feature_out='mutual_color_distances',
                               exclude_basins_set=None,
                               include_basins_set=None,
                               normalize=True,
                               sample_size=None,
                              ):
        color_space, basin_colors = self.feature_stash[basin_colors_feature]
        basin_key_set = set(basin_colors)
        if exclude_basins_set is None:
            exclude_basins_set = set()
        else:
            exclude_basins_set = set(exclude_basins_set)
        basin_key_set -= exclude_basins_set
        if include_basins_set is not None:
            include_basins_set = set(include_basins_set)
            basin_key_set &= include_basins_set
        basin_keys = sorted(tuple(basin_key_set))
        mutual_distances = {}
        for basin_A, basin_B in combinations_with_replacement(basin_keys, 2):
            assert (basin_A, basin_B) not in mutual_distances
            if basin_A == basin_B:
                mutual_distances[(basin_A, basin_B)] = 0.0
            else:
                pixels_A = basin_colors[basin_A]
                pixels_B = basin_colors[basin_B]
                if sample_size is not None:
                    sample_size_A = min(sample_size, len(pixels_A))
                    sample_size_B = min(sample_size, len(pixels_B))
                    pixels_A = sample(pixels_A, sample_size_A)
                    pixels_B = sample(pixels_B, sample_size_B)
                mutual_distance = Plate.nn_cluster_distance(
                                                           pixels_A,
                                                           pixels_B,
                                                           normalize=normalize,
                                                           )
                mutual_distances[(basin_A, basin_B)] = mutual_distance
        self.feature_stash[feature_out] = mutual_distances
        return None, self.feature_stash[feature_out]

    def rescale_image(self,
                      tag_in,
                      tag_out,
                      scaling_factor=None,
                      target_height=None,
                      target_width=None,
                     ):
        if ((scaling_factor is None)
            ^ (target_height is None)
            ^ (target_width is None)
           ):
            raise ValueError("Scaling parameters ambiguous.")
        image = self.image_stash[tag_in]
        image_height, image_width = image.shape[:2]
        if target_height is not None:
            scaling_factor = float(target_height) / image_height
        elif target_width is not None:
            scaling_factor = float(target_width) / image_width
        rescaled_image = rescale(image=image,
                                 scale=scaling_factor,
                                 mode='reflect',
                                 multichannel=True,
                                 anti_aliasing=True,
                                )
        self.image_stash[tag_out] = rescaled_image
        return self.image_stash[tag_out], None

    @staticmethod
    def is_between(x, y, p1, p2):
        p1x, p1y = p1
        p2x, p2y = p2
        if (p1x <= x <= p2x) and (p1y <= y <= p2y):
            return True
        else:
            return False

    @staticmethod
    def fit_segments(chromaticity, calibration_segments):
        x, y = chromaticity
        euclidean_distances = {(cw1, cw2): (euclidean((x, y), (cx1, cy1)),
                                            euclidean((x, y), (cx2, cy2),
                                           )
                                           )
                               for s, (cw1, cw2, (cx1, cy1), (cx2, cy2))
                               in enumerate(calibration_segments)
                              }
        between = {s: Plate.is_between(x, y, (cx1, cy1), (cx2, cy2))
                   for s, (cw1, cw2, (cx1, cy1), (cx2, cy2))
                   in enumerate(calibration_segments)
                  }
        between_index = [s for s, b in between.items() if b]
        num_is_between = len(between_index)
        if num_is_between == 1:
            between_w1, between_w2 = calibration_segments[between_index[0]][:2]
        else:
            inverse_distance_map = defaultdict(list)
            for (cw1, cw2), (e1, e2) in euclidean_distances.items():
                inverse_distance_map[e1].append(cw1)
                inverse_distance_map[e2].append(cw2)
            smallest_distance = min(inverse_distance_map)
            between_w1 = between_w2 = inverse_distance_map[smallest_distance][0]
        #This is a hack that can be done in a much cleaner fashion.
        calibration_wells = ([cw1
                              for s, (cw1, cw2, (cx1, cy1), (cx2, cy2))
                              in enumerate(calibration_segments)]
                             + [calibration_segments[-1][1]]
                            )
        num_wells = len(calibration_wells)
        num_left = 0
        for well in calibration_wells:
            if well != between_w1:
                num_left += 1
            else:
                break
        num_right = num_wells - num_left
        return between_w1, between_w2, num_left, num_right

    @staticmethod
    def point_line_distance_v2(point, line):
        p1, p2 = line
        return norm(np.cross(p2 - p1, p1 - point))/norm(p2 - p1)

    @staticmethod
    def project_point_on_segment(point,
                                 segment,
                                ):
        point = shapely.geometry.Point(point)
        segment = shapely.geometry.LineString(segment)
        np = segment.interpolate(segment.project(point))
        return np.x, np.y

    @staticmethod
    def make_boolean_circle(image,
                            h, w,
                            radius,
                           ):
        h, w, radius = int(round(h)), int(round(w)), int(round(radius))
        image_height, image_width = image.shape[:2]
        hh, ww = np.mgrid[:image_height,:image_width]
        radial_distance_sq = (hh - h)**2 + (ww - w)**2
        boolean_circle_array = (radial_distance_sq <= radius**2)
        return boolean_circle_array

    @staticmethod
    def best_circle(image,
                    basins,
                    basin,
                    radius,
                   ):
        best_h, best_w, best_circle, best_value = None, None, None, None
        for (h, w), b in np.ndenumerate(basins):
            if b != basin:
                continue
            boolean_circle = Plate.make_boolean_circle(image=image,
                                                       h=h, w=w,
                                                       radius=radius,
                                                      )
            circle_sum = np.sum(np.where(boolean_circle, image, 0))
            circle_area = np.sum(np.where(boolean_circle, 1, 0))
            #If raw intensity used, circles partially out of bounds score best
            circle_value = circle_sum / float(circle_area)
            if best_value is None or circle_value < best_value:
                best_h = h
                best_w = w
                best_circle = boolean_circle
                best_value = circle_value
        return best_h, best_w, best_circle, best_value

    def find_blobs(self,
                   tag_in,
                   feature_out='blobs_log',
                   min_sigma=1,
                   max_sigma=50,
                   num_sigma=10,
                   threshold=0.2,
                   overlap=0.5,
                   log_scale=False,
                  ):
        image = self.image_stash[tag_in]
        blobs_log = blob_log(image=image,
                             min_sigma=min_sigma,
                             max_sigma=min_sigma,
                             num_sigma=num_sigma,
                             threshold=threshold,
                             overlap=overlap,
                             log_scale=log_scale,
                            )
        self.feature_stash[feature_out] = blobs_log
        return None, self.feature_stash[feature_out]
