import os
import logging

import porepy as pp
import numpy as np
import scipy.sparse as sps
from porepy.models.contact_mechanics_biot_model import ContactMechanicsBiot

import GTS as gts


class ContactMechanicsBiotISC(ContactMechanicsBiot):
    def __init__(self, mesh_args, folder_name, **kwargs):
        """ Initialize the Contact Mechanics Biot

        Parameters
        mesh_args : dict
            Mesh arguments
        folder_name : str
            absolute path to storage folder
            Stored in self.viz_folder_name
        kwargs
            time_step : float : Default = 1
                size of a time step (post-scaled to self.length_scale ** 2)
            num_steps : int : Default = 2
                Total number of time steps
            data_path : str
                path to isc_data: path/to/GTS/01BasicInputData
        """
        self.name = "contact mechanics biot on ISC dataset"
        logging.info(f"Running: {self.name}")

        if not os.path.exists(folder_name):
            os.makedirs(folder_name, exist_ok=True)
        logging.info(f"Visualization folder path: {folder_name}")

        params = {'folder_name': folder_name}

        super().__init__(params)
        self.file_name = 'main_run'

        # Time
        self._set_time_parameters()

        # Scaling coefficients
        # self.scalar_scale = 10 * pp.GIGA
        # self.length_scale = 50

        # Grid
        self.gb = None
        self.Nd = None

        # Boundary conditions, initial conditions, source conditions:
        # Scalar source
        self.source_scalar_borehole_shearzone = {
            "shearzone": "S1_1",
            "borehole": "INJ1",
        }

        # Fractures are created in the order of self.shearzone_names.
        # This is effectively an index of the shearzone at hand.
        default_shearzone_set = ["S1_1", "S1_2", "S1_3", "S3_1", "S3_2"]
        self.shearzone_names = kwargs.get("shearzone_names", default_shearzone_set)

        # Mesh size arguments
        self.mesh_args = mesh_args

        # Bounding box of the domain
        default_box = {
            "xmin": -6,
            "xmax": 80,
            "ymin": 55,
            "ymax": 150,
            "zmin": 0,
            "zmax": 50,
        }
        self.box = kwargs.get("box", default_box)

        # TODO: Think of a good way to include ISCData in this class
        self.isc = gts.ISCData(path=kwargs.get("data_path", "linux"))

        # Tag the well cells
        self.well_cells()

    def create_grid(self, overwrite_grid=False):
        """ Create a GridBucket of a 3D domain with fractures
        defined by the ISC dataset.

        Parameters
        overwrite_grid : bool
            Overwrite an existing grid.

        The method requires the following attribute:
            mesh_args (dict): Containing the mesh sizes.

        The method assigns the following attributes to self:
            gb (pp.GridBucket): The produced grid bucket.
            box (dict): The bounding box of the domain, defined through minimum and
                maximum values in each dimension.
            Nd (int): The dimension of the matrix, i.e., the highest dimension in the
                grid bucket.

        """
        if (self.gb is None) or overwrite_grid:
            network = gts.fracture_network(
                shearzone_names=self.shearzone_names,
                export=True,
                path="linux",
                domain=self.box,
            )
            path = f"{self.path}/gmsh_frac_file"
            self.gb = network.mesh(mesh_args=self.mesh_args, file_name=path)
            pp.contact_conditions.set_projections(self.gb)
            self.Nd = self.gb.dim_max()

            # TODO: Make this procedure "safe".
            #   E.g. assign names by comparing normal vector and centroid.
            #   Currently, we assume that fracture order is preserved in creation process.
            #   This may be untrue if fractures are (completely) split in the process.
            # Set fracture grid names:
            self.gb.add_node_props(keys="name")  # Add 'name' as node prop to all grids.
            fracture_grids = self.gb.get_grids(lambda g: g.dim == 2)
            for i, sz_name in enumerate(self.shearzone_names):
                self.gb.set_node_prop(fracture_grids[i], key="name", val=sz_name)
            # Use self.gb.node_props(g, 'name') to get value.
        else:
            assert self.Nd is not None

            # We require that 2D grids have a name.
            g = self.gb.get_grids(lambda g: g.dim == 2)
            for i, sz in enumerate(self.shearzone_names):
                assert self.gb.node_props(g[i], "name") is not None

    def bc_type_mechanics(self, g):
        # TODO: Custom mechanics boundary conditions (type).
        return super().bc_type_mechanics(g)

    def bc_values_mechanics(self, g):
        # TODO: Customer mechanics boundary conditions (values).
        return super().bc_values_mechanics(g)

    def bc_values_scalar(self, g):
        """ Set boundary values to 1 (Neumann) on top face.
        0 (Dirichlet) on bottom face.
        0 (Neumann) otherwise.
        """
        # TODO: Hydrostatic scalar BC's (values).
        all_bf, east, west, north, south, top, bottom = self.domain_boundary_sides(g)
        top_face = np.nonzero(top)[0]
        bc_val = np.zeros(g.num_faces)
        bc_val[top_face] = 1
        return bc_val

    def bc_type_scalar(self, g):
        """ Set boundary conditions dirichlet on bottom face.
        Neumann otherwise.
        """
        # TODO: Hydrostatic scalar BC's (type).
        # Define boundary regions
        all_bf, east, west, north, south, top, bottom = self.domain_boundary_sides(g)
        bottom_face = np.nonzero(bottom)[0]
        # Define boundary condition on faces
        return pp.BoundaryCondition(g, bottom_face, "dir")

    # TODO: Ask if this is correct? How to assign source flow rate?
    #   borrowed from porepy-paper.
    def source_flow_rate(self):
        """
        Rate given in l/s = m^3/s e-3. Length scaling needed to convert from
        the scaled length to m.
        """
        liters = 3
        return liters * pp.MILLI * (pp.METER / self.length_scale) ** self.Nd

    def well_cells(self):
        """
        Tag well cells with unity values, positive for injection cells and
        negative for production cells.
        """
        df = self.isc.borehole_plane_intersection()
        # Borehole-shearzone intersection of interest
        bh_sz = self.source_scalar_borehole_shearzone

        _mask = (df.shearzone == bh_sz["shearzone"]) & (
                df.borehole == bh_sz["borehole"]
        )
        result = df.loc[_mask, ("x_sz", "y_sz", "z_sz")]
        if result.empty:
            raise ValueError("No intersection found.")

        pts = result.to_numpy().T
        assert pts.shape[1] == 1, "Should only be one intersection"


        for g, d in self.gb:
            tags = np.zeros(g.num_cells)

            # Get name of grid
            grid_name = self.gb.node_props(g, "name")

            # We only tag cells in the desired fracture
            if grid_name == bh_sz['shearzone']:

                logging.info(f"Grid of name: {grid_name}, and dimension {g.dim}")
                logging.info(f"Setting non-zero source for scalar variable")

                ids, dsts = g.closest_cell(pts, return_distance=True)
                logging.info(f"Closest cell found has distance: {dsts[0]:4f}")

                # Tag the injection cell
                tags[ids] = 1

            g.tags["well_cells"] = tags
            pp.set_state(d, {"well": tags.copy()})

    def source_scalar(self, g: pp.Grid):
        """ Well-bore source

        This is an example implementation of a borehole-fracture source.
        """
        flow_rate = self.source_flow_rate()

        # TODO: Ask if scalar source must be multiplied by time_step.
        values = flow_rate * g.tags["well_cells"] * self.time_step
        return values

    def set_mu(self, g):
        """ Set mu

        Set mu in linear elasticity stress-strain relation.
        stress = mu * trace(eps) + 2 * lam * eps
        """
        # TODO: Custom mu
        return np.ones(g.num_cells)

    def set_lam(self, g):
        """ Set lambda

        Set lambda in linear elasticity stress-strain relation.
        stress = mu * trace(eps) + 2 * lam * eps
        """
        # TODO: Custom lambda
        return np.ones(g.num_cells)

    def set_mechanics_parameters(self):
        """
        Set the parameters for the simulation.
        """
        gb = self.gb

        for g, d in gb:
            if g.dim == self.Nd:
                # Rock parameters
                lam = self.set_lam(g) / self.scalar_scale
                mu = self.set_mu(g) / self.scalar_scale
                C = pp.FourthOrderTensor(mu, lam)

                # Define boundary condition
                bc = self.bc_type_mechanics(g)
                # BC and source values
                bc_val = self.bc_values_mechanics(g)
                source_val = self.source_mechanics(g)

                pp.initialize_data(
                    g,
                    d,
                    self.mechanics_parameter_key,
                    {
                        "bc": bc,
                        "bc_values": bc_val,
                        "source": source_val,
                        "fourth_order_tensor": C,
                        "time_step": self.time_step,
                        "biot_alpha": self.biot_alpha(g),
                    },
                )

            elif g.dim == self.Nd - 1:
                friction = self._set_friction_coefficient(g)
                pp.initialize_data(
                    g,
                    d,
                    self.mechanics_parameter_key,
                    {"friction_coefficient": friction, "time_step": self.time_step},
                )

        for _, d in gb.edges():
            mg = d["mortar_grid"]
            pp.initialize_data(mg, d, self.mechanics_parameter_key)

    def set_viz(self):
        """ Set exporter for visualization """
        self.viz = pp.Exporter(self.gb, name=self.file_name, folder=self.viz_folder_name)

    def export_step(self):
        """ Implementation of export step"""
        export_fields = [self.displacement_variable + "_", self.scalar_variable]
        self.viz.write_vtk(export_fields, time_step=self.current_step)

    def export_pvd(self):
        """ Implementation of export pvd"""
        self.viz.write_pvd(self.export_times)

    def _set_time_parameters(self):
        """
        Set time parameters

        """
        self.time = 0
        self.time_step = 6 * pp.HOUR
        self.end_time = 2 * pp.DAY
        # Set initial time step
        self.initial_time_step = self.time_step

        num_steps = 2
        self.time_step = 1 * self.length_scale ** 2
        self.end_time = self.time_step * (num_steps - 1)
        self.time_steps_array = np.linspace(start=0, stop=self.end_time, num=num_steps)
        self.step_count = np.arange(len(self.time_steps_array))
        self.current_step = self.step_count[0]


def prepare_model(
        viz_folder_name: str = None
):
    """Prepare the ContactMechanicsBiotISC solver for the porepy run_model method.

     Parameters
     viz_folder_name : str
        Absolute path to storage folder.
    """
    if viz_folder_name is None:
        viz_folder_name = (
            "/home/haakon/mastersproject/src/mastersproject/GTS/isc_modelling/results/cm_biot_1"
        )

    # Define mesh sizes for grid generation.
    mesh_size = 5  # .36
    mesh_args = {
        "mesh_size_frac": mesh_size,
        "mesh_size_min": 0.1 * mesh_size,
        "mesh_size_bound": 6 * mesh_size,
    }

    setup = ContactMechanicsBiotISC(
        mesh_args=mesh_args,
        folder_name=viz_folder_name
    )

    # Below is pasted the relevant parts of pp.run_time_dependent_model

    # Assign parameters, variables and discretizations. Discretize time-indepedent terms
    setup.prepare_simulation()
    setup.set_viz()  # Overwrite the viz created in pp.contact_mechanics_biot at prepare_simulation()



def run_model(
        model: ContactMechanicsBiotISC = None,
        viz_folder_name: str = None,
        file_name: str = "test_biot"):
    """ Set up and run the biot model.

    Parameters
    model : ContactMechanicsBiotISC, Optional
        input model
    viz_folder_name : str
        Absolute path to storage folder.
    file_name : str
        root name of output files
    """
    if viz_folder_name is None:
        viz_folder_name = (
            "/home/haakon/mastersproject/src/mastersproject/GTS/isc_modelling/results/cm_biot_1"
        )

    # Define mesh sizes for grid generation.
    mesh_size = 5  # .36
    mesh_args = {
        "mesh_size_frac": mesh_size,
        "mesh_size_min": 0.1 * mesh_size,
        "mesh_size_bound": 6 * mesh_size,
    }

    if model is None:
        model = ContactMechanicsBiotISC(
            mesh_args=mesh_args,
            folder_name=viz_folder_name
        )

    model.prepare_simulation()
    model.set_viz()  # Overwrite the viz created in pp.contact_mechanics_biot at prepare_simulation()
    time_steps = model.time_steps_array

    # breakpoint()
    print("Starting simulation...")
    tol = 1e-10

    # Get fracture grid(s):
    # Set zero values there to facilitate export.
    frac_dims = [1, 2]
    for dim in frac_dims:
        gd_list = model.gb.grids_of_dimension(dim)
        for g in gd_list:
            data = model.gb.node_props(g)
            data[pp.STATE]["u_"] = np.zeros((3, g.num_cells))

    # Get the 3D data.
    g3 = model.gb.grids_of_dimension(3)[0]
    d3 = model.gb.node_props(g3)
    # Solve problem
    errors = []
    t_end = model.end_time
    k = 0
    while model.time < t_end:
        model.time += model.time_step
        k += 1
        logging.debug(
            f"\n Time step {k} at time {model.time:.1e} of {t_end:.1e} with time step {model.time_step:.1e}"
        )

        # Prepare for Newton

        x = model.assemble_and_solve_linear_system(tol)  # Solve time step
        # TODO: Overwrite method and save errors and iteration counter.
        model.after_newton_convergence(x, None, None)  # Distribute solution

        # Get the state, transform it, and save to another state variable
        sol3 = d3[pp.STATE][model.displacement_variable]
        trsol3 = np.reshape(np.copy(sol3), newshape=(g3.dim, g3.num_cells), order="F")
        d3[pp.STATE][model.displacement_variable + "_"] = trsol3

        # breakpoint()

        model.export_step()

    print("Successful simulation.")
    model.export_pvd()

    return model
