#
#  Copyright 2019 California Institute of Technology
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
# ISOFIT: Imaging Spectrometer Optimal FITting
# Author: Niklas Bohn, urs.n.bohn@jpl.nasa.gov
#         Jouni Susiluoto, jouni.i.susiluoto@jpl.nasa.gov
#

import logging

import h5py
import numpy as np
import yaml

from isofit import ray
from isofit.configs.sections.radiative_transfer_config import (
    RadiativeTransferEngineConfig,
)
from isofit.core.common import combos, spectral_response_function
from isofit.radiative_transfer.radiative_transfer_engine import RadiativeTransferEngine

Logger = logging.getLogger(__file__)

# This is a tempoary key mapping until we align the KF and Isofit key names
# and get KF to store the key names in the jld2 file
KEYMAPPING = {
    1: {
        "name": "AERFRAC2",
        "default_grid": [0.08, 0.2, 0.4, 0.6, 0.8, 1.0],
        "default": 0.08,
    },
    2: {
        "name": "H2OSTR",
        "default_grid": [0.05, 0.75, 1.5, 2.25, 3.0, 3.75, 4.5],
        "default": 0.05,
    },
    3: {"name": "surface_elevation_km", "default_grid": [0.0, 1.5, 3.0, 4.5, 6.0]},
    4: {"name": "observer_altitude_km", "default_grid": [0.5, 1, 2, 5, 10, 20, 100]},
    5: {"name": "solar_zenith", "default_grid": [0.0, 15.0, 30.0, 45.0, 60.0, 75.0]},
    6: {"name": "observer_zenith", "default_grid": [0.0, 10.0, 20.0, 30.0, 40.0]},
    7: {
        "name": "relative_azimuth",
        "default_grid": [0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0],
    },
    8: {"name": "solar_azimuth", "default_grid": [1, 91, 181, 271]},
    9: {"name": "observer_azimuth", "default_grid": [1, 91, 181, 271]},
}


def predict_M(
    M_Z,
    M_lambda,
    M_theta,
    M_h,
    points,
    G_Xproj_vectors,
    G_Xproj_values,
    G_Xmean,
    G_Xstd,
):
    Z_tr = M_Z.T  # training inputs

    Z_te = reduce_points(points, G_Xproj_vectors, G_Xproj_values, G_Xmean, G_Xstd)
    Z_te = Z_te * M_lambda  # scale test inputs
    theta = M_theta

    # RBF component to cross covariance matrix. Start by computing
    # Euclidean distances between testing and training inputs
    wb = np.sqrt(
        (-2 * (Z_tr @ Z_te.T).T + np.sum(Z_tr * Z_tr, axis=1)).T
        + np.sum(Z_te * Z_te, axis=1)
    )

    # Figure out a way to read kernel type from M["kernel"]["k"]
    # Matern32
    wb = np.sqrt(3.0) / theta[1] * wb  # h in kernel_functions.jl
    wb = theta[0] * (1.0 + wb) * np.exp(-wb)
    # Matern52
    # wb = sqrt(5.) / theta[1] * wb # h in kernel_functions.jl
    # wb = theta[0] * (1. + wb + wb**2 / sqrt(3.)) * exp(-wb)

    # linear component to cross covariance matrix
    wb2 = theta[2] * Z_tr @ Z_te.T
    return (wb + wb2).T @ M_h


def reduce_points(points, Xproj_vectors, Xproj_values, Xmu, Xsigma):
    Z = (points - Xmu) / Xsigma
    H = Xproj_vectors.T / Xproj_values
    return Z @ H


class KernelFlowsRT(RadiativeTransferEngine):
    """
    Radiative transfer emulation based on KernelFlows.jl and VSWIREmulator.jl. A description of
    the model can be found in:

        O. Lamminpää, J. Susiluoto, J. Hobbs, J. McDuffie, A. Braverman, and H. Owhadi.
        Forward model emulator for atmospheric radiative transfer using Gaussian processes
        and cross validation (2024). Submitted to Atmospheric Measurement Techniques.
    """

    def __init__(self, engine_config: RadiativeTransferEngineConfig, **kwargs):

        # read VSWIREmulator struct from jld2 file into a dictionary
        self.f = self.h5_to_dict(h5py.File(engine_config.emulator_file, "r"))

        self.emulator_wl = self.f["wls"]
        self.emulator_internal_idx = self.f["inputdims"].astype(int)
        self.emulator_names = [
            KEYMAPPING[i]["name"] for i in self.emulator_internal_idx
        ]
        self.points_bound_min = self.f["xmin"]
        self.points_bound_max = self.f["xmax"]

        with open(engine_config.template_file, "r") as tpl_f:
            template = yaml.safe_load(tpl_f)
        try:
            # global KEYMAPPING
            KEYMAPPING[3]["default"] = template["MODTRAN"][0]["MODTRANINPUT"][
                "SURFACE"
            ]["GNDALT"]
        except:
            logging.info("No surface_elevation_km default in template")

        try:
            KEYMAPPING[4]["default"] = template["MODTRAN"][0]["MODTRANINPUT"][
                "GEOMETRY"
            ]["H1ALT"]
        except:
            logging.info("No observer_altitude_km default in template")

        try:
            KEYMAPPING[5]["default"] = template["MODTRAN"][0]["MODTRANINPUT"][
                "GEOMETRY"
            ]["PARM2"]
        except:
            logging.info("No solar_zenith default in template")

        try:
            KEYMAPPING[6]["default"] = template["MODTRAN"][0]["MODTRANINPUT"][
                "GEOMETRY"
            ]["OBSZEN"]
        except:
            logging.info("No observer_zenith default in template")

        try:
            KEYMAPPING[7]["default"] = template["MODTRAN"][0]["MODTRANINPUT"][
                "GEOMETRY"
            ]["TRUEAZ"]
        except:
            logging.info("No relative_azimuth default in template")

        try:
            KEYMAPPING[8]["default"] = template["MODTRAN"][0]["MODTRANINPUT"][
                "GEOMETRY"
            ]["PARM1"]
        except:
            logging.info("No solar_azimuth default in template")

        # defining some input transformations
        self.input_transfs = [
            np.identity,
            np.log,
            lambda x: np.cos(np.deg2rad(x)),
            lambda x: np.cos(np.deg2rad(90 - x)),
            lambda x: np.log(180 - x),
        ]
        self.output_transfs = [
            lambda x: np.exp(x) - 0.1,
        ]

        # Run super now....we need the lut_grid to go on
        super().__init__(engine_config, **kwargs)
        self.assign_bounds()

    def assign_bounds(self):
        try:
            lut_grid_keynames = [x for x in self.lut_grid.keys()]
            self.point_inds_to_emulator_inds = [
                lut_grid_keynames.index(i) if i in lut_grid_keynames else -1
                for i in self.emulator_names
            ]
            logging.info(f"lut_grid_keynames: {lut_grid_keynames}")
            logging.info(f"emulator_names: {self.emulator_names}")
            logging.info(
                f"point_inds_to_emulator_inds: {self.point_inds_to_emulator_inds}"
            )
        except:
            outstr = "The provided emulator is missing lut keys: {[i for i in emulator_names if i not in self.lut_grid.keys()]}"
            raise ValueError(outstr)

    def h5_to_dict(self, file):
        outdict = {}
        for key, val in file.items():
            if type(val) == h5py._hl.dataset.Dataset:
                outdict[key] = np.array(val)
            else:
                outdict[key] = self.h5_to_dict(val)
        return outdict

    def preSim(self):
        logging.info(f"KF Presim")
        self.srf_matrix = np.array(
            [
                spectral_response_function(self.emulator_wl, wi, fwhmi / 2.355)
                for wi, fwhmi in zip(self.wl, self.fwhm)
            ]
        )
        self.ga = list()

        # KF requires an exact specification of keys.  Possible failure modes include:
        # KF has keys not in lut_grid
        # lut_grid has keys not in KF - for this one, we should insert something.  Ideally, a
        # mean from the config file, but for now just put a grid of reasonable values.  Set these
        # values as -1 for later lookup

        # self.default_lut_grid = {
        #     "AOT550": [0.001, 0.2, 0.4, 0.6, 0.8, 1.0],
        #     "surface_elevation_km": [0.0, 1.5, 3.0, 4.5, 6.0],
        #     "H2OSTR": [0.05, 0.75, 1.5, 2.25, 3.0, 3.75, 4.5],
        #     "relative_azimuth": [0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0],
        #     "solar_zenith": [0.0, 15.0, 30.0, 45.0, 60.0, 75.0],
        #     "observer_zenith": [0.0, 10.0, 20.0, 30.0, 40.0],
        # }
        default_lut_grid = {}
        default_lut_val = {}
        for key in self.emulator_internal_idx:
            logging.info(KEYMAPPING[key])
            default_lut_grid[KEYMAPPING[key]["name"]] = KEYMAPPING[key]["default_grid"]
            default_lut_val[KEYMAPPING[key]["name"]] = KEYMAPPING[key]["default"]

        logging.info(f"Default lut grid: {default_lut_grid}")
        logging.info(f"Default lut val: {default_lut_val}")
        self.lut_points = []

        for ii, key in enumerate(self.emulator_names):
            logging.info(f"Checking key {key}")
            logging.info(f"lut_grid keys: {self.lut_grid.keys()}")
            if key in self.lut_grid.keys():
                if len(self.lut_grid[key]) > 1:
                    self.lut_points.append(self.lut_grid[key])
                elif len(self.lut_grid[key]) == 1:
                    prevpoint = self.lut_grid[key][0]
                    adjustment = [
                        self.lut_grid[key][0] * 0.99,
                        self.lut_grid[key][0],
                        self.lut_grid[key][0] * 1.01,
                    ]
                    self.lut_points.append(adjustment)
                    self.lut_grid[key] = adjustment
                    logging.info(
                        f"adjusting lut grid {key} from {prevpoint} to {adjustment}"
                    )
            else:
                adjustment = [default_lut_val[key]]
                self.lut_points.append(adjustment)
                self.lut_grid[key] = adjustment
                logging.info(f"No grid point for {key}, using template: {adjustment}")

        self.points = combos(self.lut_points)
        self.assign_bounds()
        return False

    def makeSim(self, point: np.array, template_only: bool = False):
        # Kernel Flows doesn't need to make the simulation, as it can execute
        # directly
        pass

    def readSim(self, in_point):
        # shuffle point based on emulator dims
        # point = in_point[self.point_inds_to_emulator_inds]
        point = in_point

        if np.any(point < self.points_bound_min) or np.any(
            point > self.points_bound_max
        ):
            outstr = f"Input point is out of bounds. \n keys: {self.emulator_names} \n point: {point} \n xmin: {self.points_bound_min} \n xmax: {self.points_bound_max} \n oob_low: {point < self.points_bound_min} \n oob_high: {point > self.points_bound_max}"
            raise ValueError(outstr)

        nMVMs = len(self.f.keys()) - 6
        for i in range(1, 1 + nMVMs):
            MVM = self.predict_single_MVM(
                self.f["MVM" + str(i)], point, self.f["input_transfs"][i - 1, :]
            )
            self.ga.append(MVM)
        ga_1 = self.output_transfs[0](self.ga[1][:, :])
        ga_2 = self.output_transfs[0](self.ga[2][:, :])

        combined = {
            "rhoatm": self.ga[0],
            "sphalb": self.ga[3],
            "transm_down_dir": ga_1,
            "transm_down_dif": ga_2,
            "transm_up_dir": np.zeros(self.ga[0].shape),
            "transm_up_dif": np.zeros(self.ga[0].shape),
            "thermal_upwelling": np.zeros(self.ga[0].shape),
            "thermal_downwelling": np.zeros(self.ga[0].shape),
            "solar_irr": np.zeros(self.wl.shape),
            "wl": self.wl,
        }
        return combined

    def predict(self, points):

        if np.any(points < self.points_bound_min) or np.any(
            points > self.points_bound_max
        ):
            outstr = f"Input points are out of bounds xmin: {self.points_bound_min}, xmax: {self.points_bound_max}"
            raise ValueError(outstr)

        nMVMs = len(self.f.keys()) - 6
        for i in range(1, 1 + nMVMs):
            MVM = self.predict_single_MVM(
                self.f["MVM" + str(i)], points, self.f["input_transfs"][i - 1, :]
            )
            self.ga.append(MVM)

        # back-transform some quantities from log space
        # ToDo: this might not always be needed,
        #  so we need an if-statement at some point
        ga_1 = self.output_transfs[0](self.ga[1][:, :])
        ga_2 = self.output_transfs[0](self.ga[2][:, :])

        combined = {
            "rhoatm": self.ga[0],
            "sphalb": self.ga[3],
            "transm_down_dir": ga_1,
            "transm_down_dif": ga_2,
            "transm_up_dir": np.zeros(self.ga[0].shape),
            "transm_up_dif": np.zeros(self.ga[0].shape),
            "thermal_upwelling": np.zeros(self.ga[0].shape),
            "thermal_downwelling": np.zeros(self.ga[0].shape),
            "solar_irr": np.zeros(self.wl.shape),
            "wl": self.wl,
        }
        return combined

    def predict_single_MVM(self, MVM, points, transfs):
        points = np.copy(points)  # don't overwrite inputs
        if len(points.shape) == 1:
            points = points.reshape(1, -1)
        for i, j in enumerate(transfs):
            if j == 1:
                continue
            points[:, i] = self.input_transfs[j - 1](points[:, i])

        nte = np.shape(points)[0]
        nzycols = len(MVM.keys()) - 1  # take out GPGeometry from list of GPs
        ZY_pred = np.zeros((nte, nzycols))

        logging.info(f"Parallel KF application across {len(range(nzycols))} nzycols")

        ZY_out = []
        for i in range(nzycols):
            M = MVM["M" + str(i + 1)]
            G = MVM["G"]  # shorthand
            M_Z = np.array(M["Z"])
            M_lambda = np.array(M["lambda"])
            M_theta = np.array(M["theta"])
            M_h = np.array(M["h"])
            G_Xproj_vectors = np.array(G["Xproj" + str(i + 1)]["vectors"])
            G_Xproj_values = np.array(G["Xproj" + str(i + 1)]["values"])
            G_Xmean = np.array(G["Xmean"])
            G_Xstd = np.array(G["Xstd"])

            ZY_out.append(
                predict_M(
                    M_Z,
                    M_lambda,
                    M_theta,
                    M_h,
                    points,
                    G_Xproj_vectors,
                    G_Xproj_values,
                    G_Xmean,
                    G_Xstd,
                )
            )
        for i in range(len(ZY_out)):
            ZY_pred[:, i] = ZY_out[i]
        del ZY_out

        # H is same as in recover() in dimension_reduction.jl
        MP = self.srf_matrix @ G["Yproj"]["vectors"][:, :].T
        H = MP * G["Yproj"]["values"][:]
        srfmean = self.srf_matrix @ G["Ymean"]
        return (ZY_pred @ H.T) * G["Ystd"] + srfmean
