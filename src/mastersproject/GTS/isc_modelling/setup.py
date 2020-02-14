import os
import logging
from typing import (  # noqa
    Any,
    Coroutine,
    Generator,
    Generic,
    Iterable,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)
from pathlib import Path

import pendulum
import porepy as pp
import numpy as np
import scipy.sparse as sps
from porepy.models.contact_mechanics_biot_model import ContactMechanicsBiot

import GTS as gts
from refinement import refine_mesh

# --- LOGGING UTIL ---
from util.logging_util import timer, trace
# logger = logging.getLogger(__name__)


def __setup_logging(path, log_fname="results.log"):
    path = str(path)
    # GTS logger
    gts_logger = logging.getLogger('GTS')
    gts_logger.setLevel(logging.INFO)

    # PorePy logger
    pp_logger = logging.getLogger('porepy')
    pp_logger.setLevel(logging.DEBUG)

    # Add handler for logging debug messages to file.
    fh = logging.FileHandler(path + "/" + log_fname)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(logging.BASIC_FORMAT))

    gts_logger.addHandler(fh)
    pp_logger.addHandler(fh)


@timer
@trace
def run_biot_model(
        *,
        viz_folder_name: str = None,
        result_file_name: str = None,
        isc_data_path: str = None,
        mesh_args: Mapping[str, int] = None,
        bounding_box: Mapping[str, int] = None,
        shearzone_names: List[str] = None,
        source_scalar_borehole_shearzone: Mapping[str, str] = None,
        scales: Mapping[str, float] = None,
):
    """ Send all initialization parameters to contact mechanics biot class

        Parameters
        ----------
        viz_folder_name : str
            Absolute path to folder where grid and results will be stored
            Default: /home/haakon/mastersproject/src/mastersproject/GTS/isc_modelling/results/default
        result_file_name : str
            Root name for simulation result files
            Default: 'main_run'
        isc_data_path : str
            Path to isc data: path/to/GTS/01BasicInputData
            Alternatively 'linux' or 'windows' for certain default paths (only applies to haakon's computers).
            Default: 'linux'
        mesh_args : Mapping[str, int]
            Arguments for meshing of domain.
            Required keys: 'mesh_size_frac', 'mesh_size_min, 'mesh_size_bound'
        bounding_box : Mapping[str, int]
            Bounding box of domain
            Required keys: 'xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'.
        shearzone_names : List[str]
            Which shear-zones to include in simulation
        source_scalar_borehole_shearzone : Mapping[str, str]
            Which borehole and shear-zone intersection to do injection in.
            Required keys: 'shearzone', 'borehole'
        scales : Mapping[str, float]
            Length scale and scalar variable scale.
            Required keys: 'scalar_scale', 'length_scale'
            Defaults to 1 for both.
        """
    # ------------------------------------------
    # --- FOLDER AND FILE RELATED PARAMETERS ---
    # ------------------------------------------

    # TODO: Create different folders for each phase.
    # Set viz folder
    if viz_folder_name is None:
        viz_folder_name = (
            "/home/haakon/mastersproject/src/mastersproject/GTS/isc_modelling/results/new_biot/default"
        )
    viz_folder_name = str(viz_folder_name)
    # Create viz folder path if it does not already exist
    if not os.path.exists(viz_folder_name):
        os.makedirs(viz_folder_name, exist_ok=True)

    # Set up logging
    __setup_logging(viz_folder_name)
    # logging.basicConfig(filename=viz_folder_name + "/results.log", level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.info(f"Preparing setup for mechanics simulation on {pendulum.now().to_atom_string()}")
    logger.info(f"Visualization folder path: \n {viz_folder_name}")

    # Set file name of modelling results files
    # if result_file_name is None:
    #     result_file_name = 'main_run'
    # logger.info(f"Root file name of results: {result_file_name}")

    # Get data path to ISC data
    if isc_data_path is None:
        isc_data_path = 'linux'

    # ------------------------------------
    # --- MODELLING RELATED PARAMETERS ---
    # ------------------------------------

    # Set mesh arguments
    if mesh_args is None:
        # mesh_size = 10
        # mesh_args = {  # A very coarse grid
        #     "mesh_size_frac": mesh_size,
        #     "mesh_size_min": mesh_size,
        #     "mesh_size_bound": mesh_size,
        # }
        sz = 10
        mesh_args = {'mesh_size_frac': sz,
                     'mesh_size_min': 0.1 * sz,
                     'mesh_size_bound': 6 * sz}
    logger.info(f"Mesh arguments: \n {mesh_args}")

    # Set bounding box
    if bounding_box is None:
        bounding_box = {
            "xmin": -6,
            "xmax": 80,
            "ymin": 55,
            "ymax": 150,
            "zmin": 0,
            "zmax": 50,
        }
    logger.info(f"Bounding box: \n {bounding_box}")

    # Set which shear-zones to include in simulation
    if shearzone_names is None:
        shearzone_names = ["S1_1", "S1_2", "S1_3", "S3_1", "S3_2"]
    logger.info(f"Shear zones in simulation: \n {shearzone_names}")

    # Set length scale and scalar scale
    if scales is None:
        scales = {
            'scalar_scale': 1,
            'length_scale': 1,
        }
    logger.info(f"Variable scaling: \n {scales}")

    # Set solver. 'pyamg' or 'direct'.
    solver = 'direct'
    logger.info(f"Solver type: {solver}")

    # Set which borehole / shearzone to inject fluid to
    # This corresponds to setup in HS2 from Doetsch et al 2018
    if source_scalar_borehole_shearzone is None:
        source_scalar_borehole_shearzone = {
            "shearzone": "S1_2",
            "borehole": "INJ1",
        }
    logger.info(f"Injection location: \n {source_scalar_borehole_shearzone}")

    # TODO: Set custom time parameters with a class with only one method: _set_time_parameters.
    #  Currently, this is set to something pre-determined within the ContactMechanicsBiotISC class.

    # ---------------------------
    # --- PHYSICAL PARAMETERS ---
    # ---------------------------

    stress = stress_tensor()
    logger.info(f"Stress tensor: \n {stress}")
    # -------------------
    # --- SETUP MODEL ---
    # -------------------

    setup = gts.ContactMechanicsBiotISC(
        viz_folder_name=viz_folder_name,
        # result_file_name=result_file_name,
        isc_data_path=isc_data_path,
        mesh_args=mesh_args,
        bounding_box=bounding_box,
        shearzone_names=shearzone_names,
        source_scalar_borehole_shearzone=source_scalar_borehole_shearzone,
        scales=scales,
        stress=stress,
        solver=solver,
    )
    # -------------------------
    # --- SOLVE THE PROBLEM ---
    # -------------------------
    default_options = {  # Parameters for Newton solver.
        "max_iterations": 10,
        "nl_convergence_tol": 0.98,  # WARNING: VERY HIGH CONVERGENCE TOL !!!!!!!!!!!!!!!!!!!!!!!!!!!
        "nl_divergence_tol": 1e5,
    }
    newton_options = default_options
    logger.info(f"Options for Newton solver: \n {newton_options}")

    logger.info("Setup complete. Starting time-dependent simulation")
    pp.run_time_dependent_model(setup=setup, params=default_options)
    logger.info(f"Simulation complete. Exporting solution. Time: {pendulum.now().to_atom_string()}")

    # Stimulation phase
    logger.info(f"Starting stimulation phase at time: {pendulum.now().to_atom_string()}")
    setup.prepare_main_run()

    logger.info("Setup complete. Starting time-dependent simulation")
    pp.run_time_dependent_model(setup=setup, params=default_options)
    logger.info(f"Simulation complete. Exporting solution. Time: {pendulum.now().to_atom_string()}")

    logger.info(f"Exits method on {pendulum.now().to_atom_string()}")
    return setup


@timer
@trace
def run_mechanics_model(
        *,
        viz_folder_name: str = None,
        result_file_name: str = None,
        isc_data_path: str = None,
        mesh_args: Mapping[str, int] = None,
        bounding_box: Mapping[str, int] = None,
        shearzone_names: List[str] = None,
        # source_scalar_borehole_shearzone: Mapping[str, str] = None,
        scales: Mapping[str, float] = None,

):
    """ Send all initialization parameters to contact mechanics class

    Parameters
    ----------
    viz_folder_name : str
        Absolute path to folder where grid and results will be stored
        Default: /home/haakon/mastersproject/src/mastersproject/GTS/isc_modelling/results/default
    result_file_name : str
        Root name for simulation result files
        Default: 'main_run'
    isc_data_path : str
        Path to isc data: path/to/GTS/01BasicInputData
        Alternatively 'linux' or 'windows' for certain default paths (only applies to haakon's computers).
        Default: 'linux'
    mesh_args : Mapping[str, int]
        Arguments for meshing of domain.
        Required keys: 'mesh_size_frac', 'mesh_size_min, 'mesh_size_bound'
    bounding_box : Mapping[str, int]
        Bounding box of domain
        Required keys: 'xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'.
    shearzone_names : List[str]
        Which shear-zones to include in simulation
    # source_scalar_borehole_shearzone : Mapping[str, str]
    #     Which borehole and shear-zone intersection to do injection in.
    #     Required keys: 'shearzone', 'borehole'
    scales : Mapping[str, float]
        Length scale and scalar variable scale.
        Required keys: 'scalar_scale', 'length_scale'
        Defaults to 1 for both.
    """
    # ------------------------------------------
    # --- FOLDER AND FILE RELATED PARAMETERS ---
    # ------------------------------------------

    # Set viz folder
    if viz_folder_name is None:
        viz_folder_name = (
            "/home/haakon/mastersproject/src/mastersproject/GTS/isc_modelling/results/default"
        )
    viz_folder_name = str(viz_folder_name)
    # Create viz folder path if it does not already exist
    Path(viz_folder_name).mkdir(parents=True, exist_ok=True)

    # Set up logging
    __setup_logging(viz_folder_name)
    # logging.basicConfig(filename=viz_folder_name + "/results.log", level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.info(f"Preparing setup for mechanics simulation on {pendulum.now().to_atom_string()}")
    logger.info(f"Visualization folder path: \n {viz_folder_name}")

    # Set file name of modelling results files
    if result_file_name is None:
        result_file_name = 'main_run'
    logger.info(f"Root file name of results: {result_file_name}")

    # Get data path to ISC data
    if isc_data_path is None:
        isc_data_path = 'linux'

    # ------------------------------------
    # --- MODELLING RELATED PARAMETERS ---
    # ------------------------------------

    # Set mesh arguments
    if mesh_args is None:
        mesh_size = 10
        mesh_args = {  # A very coarse grid
            "mesh_size_frac": mesh_size,
            "mesh_size_min": mesh_size,
            "mesh_size_bound": mesh_size,
        }
    logger.info(f"Mesh arguments: \n {mesh_args}")

    # Set bounding box
    if bounding_box is None:
        bounding_box = {
            "xmin": -6,
            "xmax": 80,
            "ymin": 55,
            "ymax": 150,
            "zmin": 0,
            "zmax": 50,
        }
    logger.info(f"Bounding box: \n {bounding_box}")

    # Set which shear-zones to include in simulation
    if shearzone_names is None:
        shearzone_names = ["S1_1", "S1_2", "S1_3", "S3_1", "S3_2"]
    logger.info(f"Shear zones in simulation: \n {shearzone_names}")

    # Set length scale and scalar scale
    if scales is None:
        scales = {
            'scalar_scale': 1,
            'length_scale': 1,
        }
    logger.info(f"Variable scaling: \n {scales}")

    # Set solver. 'pyamg' or 'direct'.
    solver = 'direct'
    logger.info(f"Solver type: {solver}")

    # TODO: Set custom time parameters with a class with only one method: _set_time_parameters

    # ---------------------------
    # --- PHYSICAL PARAMETERS ---
    # ---------------------------

    stress = stress_tensor()
    logger.info(f"Stress tensor: \n {stress}")
    # -------------------
    # --- SETUP MODEL ---
    # -------------------

    setup = gts.ContactMechanicsISC(
        viz_folder_name=viz_folder_name,
        result_file_name=result_file_name,
        isc_data_path=isc_data_path,
        mesh_args=mesh_args,
        bounding_box=bounding_box,
        shearzone_names=shearzone_names,
        # source_scalar_borehole_shearzone=source_scalar_borehole_shearzone,
        scales=scales,
        stress=stress,
        solver=solver,
    )
    # -------------------------
    # --- SOLVE THE PROBLEM ---
    # -------------------------
    default_options = {  # Parameters for Newton solver.
        "max_iterations": 10,
        "convergence_tol": 1e-10,
        "divergence_tol": 1e5,
    }
    newton_options = default_options
    logger.info(f"Options for Newton solver: \n {newton_options}")

    logger.info("Setup complete. Starting simulation")
    pp.run_stationary_model(setup, params=newton_options)
    logger.info("Simulation complete. Exporting solution.")

    setup.export_step()
    logger.info(f"Solution exported to folder \n {viz_folder_name}")
    logger.info(f"Exits method on {pendulum.now().to_atom_string()}")
    return setup


def create_isc_domain(
        viz_folder_name: Union[str, Path],
        shearzone_names: List[str],
        bounding_box: dict,
        mesh_args: dict,
        n_refinements: int = 0):
    """ Create a domain (.geo file) for the ISC test site.

    Parameters
    ----------
    viz_folder_name : str or pathlib.Path
        Absolute path to folder to store results in
    shearzone_names : List of str
        Names of shearzones to include
    bounding_box : dict
        Bounding box of domain ('xmin', 'xmax', etc.)
    mesh_args : dict
        Arguments for meshing (of coarsest grid)
    n_refinements : int, Default = 0
        Number of refined grids to produce.
        The grid is refined by splitting.
    """

    # -----------------
    # --- ARGUMENTS ---
    # -----------------
    isc_data_path = 'linux'

    # ----------------------------------------
    # --- CREATE FRACTURE NETWORK AND MESH ---
    # ----------------------------------------
    network = gts.fracture_network(
        shearzone_names=shearzone_names,
        export=True,
        path=isc_data_path,
        domain=bounding_box,
    )

    gmsh_file_name = str(viz_folder_name / "gmsh_frac_file")
    gb = network.mesh(mesh_args=mesh_args, file_name=gmsh_file_name)

    gb_list = refine_mesh(
        in_file=f'{gmsh_file_name}.geo',
        out_file=f"{gmsh_file_name}.msh",
        dim=3,
        network=network,
        num_refinements=n_refinements,
    )

    # TODO: Make this procedure "safe".
    #   E.g. assign names by comparing normal vector and centroid.
    #   Currently, we assume that fracture order is preserved in creation process.
    #   This may be untrue if fractures are (completely) split in the process.
    # Assign node prop 'name' to each grid in the grid bucket.
    for _gb in gb_list:
        pp.contact_conditions.set_projections(_gb)
        _gb.add_node_props(keys="name")
        fracture_grids = _gb.get_grids(lambda g: g.dim == _gb.dim_max() - 1)
        if shearzone_names is not None:
            for i, sz_name in enumerate(shearzone_names):
                _gb.set_node_prop(fracture_grids[i], key="name", val=sz_name)
                # Note: Use self.gb.node_props(g, 'name') to get value.

    return gb_list


@timer
@trace
def convergence_study():
    """ Perform a convergence study of a given problem setup.
    """

    # 1. Step: Create n grids by uniform refinement.
    # 2. Step: for grid i in list of n grids:
    # 2. a. Step: Set up the mechanics model.
    # 2. b. Step: Solve the mechanics problem.
    # 2. c. Step: Keep the grid (with solution data)
    # 3. Step: Let the finest grid be the reference solution.
    # 4. Step: For every other grid:
    # 4. a. Step: Map the solution to the fine grid, and compute error.
    # 5. Step: Compute order of convergence, etc.

    # -----------------
    # --- ARGUMENTS ---
    # -----------------
    viz_folder_name = Path(os.path.abspath(__file__)).parent / "results/mech_convergence_2test"
    if not os.path.exists(viz_folder_name):
        os.makedirs(viz_folder_name, exist_ok=True)

    shearzone_names = ["S1_1", "S1_2", "S1_3", "S3_1", "S3_2"]

    mesh_size = 10
    mesh_args = {  # A very coarse grid
        "mesh_size_frac": mesh_size,
        "mesh_size_min": mesh_size,
        "mesh_size_bound": mesh_size,
    }

    bounding_box = {
        "xmin": -6,
        "xmax": 80,
        "ymin": 55,
        "ymax": 150,
        "zmin": 0,
        "zmax": 50,
    }

    # 1. Step: Create n grids by uniform refinement.
    gb_list = create_isc_domain(
        viz_folder_name=viz_folder_name,
        shearzone_names=shearzone_names,
        bounding_box=bounding_box,
        mesh_args=mesh_args,
        n_refinements=1,
    )

    scales = {
        'scalar_scale': 1,
        'length_scale': 1,
    }
    solver = 'direct'

    # ---------------------------
    # --- PHYSICAL PARAMETERS ---
    # ---------------------------

    stress = stress_tensor()

    # ----------------------
    # --- SET UP LOGGING ---
    # ----------------------
    print(viz_folder_name / "results.log")
    logger = __setup_logging(viz_folder_name)

    logger.info(f"Preparing setup for mechanics convergence study on {pendulum.now().to_atom_string()}")
    logger.info(f"Reporting on {len(gb_list)} grid buckets.")
    logger.info(f"Visualization folder path: \n {viz_folder_name}")
    logger.info(f"Mesh arguments for coarsest grid: \n {mesh_args}")
    logger.info(f"Bounding box: \n {bounding_box}")
    logger.info(f"Variable scaling: \n {scales}")
    logger.info(f"Solver type: {solver}")
    logger.info(f"Stress tensor: \n {stress}")

    # -----------------------
    # --- SETUP AND SOLVE ---
    # -----------------------

    newton_options = {  # Parameters for Newton solver.
        "max_iterations": 10,
        "convergence_tol": 1e-10,
        "divergence_tol": 1e5,
    }
    logger.info(f"Options for Newton solver: \n {newton_options}")

    from GTS.isc_modelling.mechanics import ContactMechanicsISCWithGrid
    for gb in gb_list:
        setup = ContactMechanicsISCWithGrid(
            viz_folder_name, 'main_run', 'linux', mesh_args, bounding_box,
            shearzone_names, scales, stress, solver, gb,
        )

        logger.info("Setup complete. Starting simulation")
        pp.run_stationary_model(setup, params=newton_options)
        logger.info("Simulation complete. Exporting solution.")

    return gb_list


def stress_tensor():
    """ Stress at ISC test site

    Values from Krietsch et al 2019
    """

    # Note: Negative side due to compressive stresses
    stress_value = - np.array([13.1, 9.2, 8.7]) * pp.MEGA * pp.PASCAL
    dip_direction = np.array([104.48, 259.05, 3.72])
    dip = np.array([39.21, 47.90, 12.89])

    def r(th, gm):
        """ Compute direction vector of a dip (th) and dip direction (gm)."""
        rad = np.pi / 180
        x = np.cos(th * rad) * np.sin(gm * rad)
        y = np.cos(th * rad) * np.cos(gm * rad)
        z = - np.sin(th * rad)
        return np.array([x, y, z])

    rot = r(th=dip, gm=dip_direction)

    # Orthogonalize the rotation matrix (which is already close to orthogonal)
    rot, _ = np.linalg.qr(rot)

    # Stress tensor in principal coordinate system
    stress = np.diag(stress_value)

    # Stress tensor in euclidean coordinate system
    stress_eucl = np.dot(np.dot(rot, stress), rot.T)
    return stress_eucl