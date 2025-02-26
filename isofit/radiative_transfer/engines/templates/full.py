"""
This is a template radiative transfer engine that can be copied and updated for a new engine.
It contains all of the pieces required to create a custom engine.

Be sure to edit engines/__init__.py to import your custom engine and set its name to be referenced via the config:
    from .full import CustomRT
    Engines['CustomRT'] = CustomRT
"""

from isofit.configs.sections.radiative_transfer_config import (
    RadiativeTransferEngineConfig,
)
from isofit.radiative_transfer.radiative_transfer_engine import RadiativeTransferEngine


class CustomRT(RadiativeTransferEngine):
    """
    This contains all of the possible pieces that can be defined.
    """

    # Disabling will also disable calls to readSim, leaving only preSim and postSim to be executed
    _disable_makeSim = False  # Default in RadiativeTransferEngine

    # Sleep a random amount of time up to max this value at the start of each streamSimulation
    max_buffer_time = 0  # Default in RadiativeTransferEngine

    def __init__(self, engine_config: RadiativeTransferEngineConfig, **kwargs):
        """
        Not required to be defined. Omit the function to use the default RadiativeTransferEngine.__init__

        The order of (possible) operations is:
            - __init__() before super()
            - preSim()
            if not self._disable_makeSim:
                - makeSim()
                - readSim()
            - postSim()
            - __init__() after super()
        """
        # Code implemented before super() will execute before anything else
        # Note that many of the attributes set by RadiativeTransferEngine in __init__ will not be available yet
        ...

        super().__init__(engine_config, **kwargs)

        # Afterwards will be after the sim functions (LUT generation)
        ...

    def preSim(self):
        """
        Required to be defined. If not desired, be sure to define the function and simply `pass`

        Executes any pre-simulation calculations. This is helpful if you need additional processing
        before makeSim after __init__, or if any serial processes must occur beforehand. sRTMnet
        contains an extentive example of this.

        This function may return a dictionary similar to the output of makeSim to be written to the LUT file,
        however this data will be mapped to point index 0. This is most useful for setting variables that are
        not on the point dimension, such as coszen, solzen, fwhm, or solar_irr.
        """
        pass

    def makeSim(self, point: np.array, template_only: bool = False):
        """
        Required to be defined. If not desired, be sure to define the function and simply `pass`

        Performs the simulation calls in parallel. This function is distributed via Ray
        for each point in the points array.
        """
        pass

    def readSim(self, point: np.array):
        """
        Required to be defined. If not desired, be sure to define the function and simply `pass`

        Reads the simulation files generated by makeSim and formats the data to be inserted into the LUT file at
        the given point. The returned data should be a dictionary where the keys are defined by one of:
            luts.Keys.consts
            luts.Keys.onedim
            luts.Keys.alldim

        `consts` are constant scalar values
        'onedim' are 1D arrays along the wavelength dimension only. The size of these is equal to the wavelengths size.
        `alldim` are 1D arrays along both the wavelength and point dimensions. The size of these is equal to the wavelengths size.

        An example return may be:
            return {
                "solzen": 1,
                "solar_irr": [1, 2, 3],
                "rhoatm": [4, 5, 6]
            }
        Where
            "solzen" is in luts.Keys.consts
            "solar_irr" is in luts.Keys.onedim, so it will be saved along the "wl" dim only
            "rhoatm" is in luts.Keys.onedim, so it will be saved along dims ("wl", "point") at the index of this `point`
        """
        pass

    def postSim(self):
        """
        Required to be defined. If not desired, be sure to define the function and simply `pass`

        Executes any post-simulation calculations. This is helpful if you need additional processing
        before makeSim after __init__, or if any serial processes must occur beforehand. sRTMnet
        contains an extentive example of this.

        This function may return a dictionary similar to the output of makeSim to be written to the LUT file,
        however this data will be mapped to point index 0. This is most useful for setting variables that are
        not on the point dimension, such as coszen, solzen, fwhm, or solar_irr.
        """
        pass

    # Additional utility functions may be defined on the class and used within any of the above functions
