import os, glob, pathlib, shutil, subprocess, logging
from pathlib import Path
from typing import List
from dflow.python import (
    OP,
    OPIO,
    OPIOSign,
    Artifact,
    upload_packages
)

from apex.op.utils import recursive_search

upload_packages.append(__file__)


class PropsMake(OP):
    """
    OP class for making calculation tasks (make property)
    """
    def __init__(self):
        pass

    @classmethod
    def get_input_sign(cls):
        return OPIOSign({
            'input_work_path': Artifact(Path),
            'path_to_prop': str,
            'prop_param': dict,
            'inter_param': dict,
            'do_refine': bool
        })

    @classmethod
    def get_output_sign(cls):
        return OPIOSign({
            'output_work_path': Artifact(Path),
            'task_names': List[str],
            'njobs': int,
            'task_paths': Artifact(List[Path])
        })

    @OP.exec_sign_check
    def execute(
            self,
            op_in: OPIO,
    ) -> OPIO:
        from ..core.common_prop import make_property_instance
        from ..core.calculator.calculator import make_calculator

        input_work_path = op_in["input_work_path"]
        path_to_prop = op_in["path_to_prop"]
        prop_param = op_in["prop_param"]
        inter_param = op_in["inter_param"]
        do_refine = op_in["do_refine"]
        
        print(inter_param)

        cwd = Path.cwd()
        os.chdir(input_work_path)
        abs_path_to_prop = input_work_path / path_to_prop
        conf_path = abs_path_to_prop.parent
        prop_name = abs_path_to_prop.name
        path_to_equi = conf_path / "relaxation" / "relax_task"
        prop = make_property_instance(prop_param, inter_param)
        task_list = prop.make_confs(abs_path_to_prop, path_to_equi, do_refine)
        for kk in task_list:
            poscar = os.path.join(kk, "POSCAR")
            inter = make_calculator(inter_param, poscar)
            inter.make_potential_files(kk)
            logging.debug(prop.task_type())  ### debug
            # if task_param has "cal_setting" key and it refers to a file, then ...
            # custom util comes here
            print(prop.task_type())
            print(prop.task_param())
            inter.make_input_file(kk, prop.task_type(), prop.task_param())
        prop.post_process(
            task_list
        )  # generate same KPOINTS file for elastic when doing VASP

        task_list.sort()
        os.chdir(input_work_path)
        task_list_str = glob.glob(path_to_prop + '/' + 'task.*')
        task_list_str.sort()

        all_jobs = task_list
        njobs = len(all_jobs)
        jobs = []
        for job in all_jobs:
            jobs.append(pathlib.Path(job))

        os.chdir(cwd)
        op_out = OPIO({
            "output_work_path": input_work_path,
            "task_names": task_list_str,
            "njobs": njobs,
            "task_paths": jobs
        })
        return op_out


#from apex.op.property_ops import PropsPost as PropPost

class PropsPost(OP):
    """
    OP class for analyzing calculation results (post property)
    """

    def __init__(self):
        pass

    @classmethod
    def get_input_sign(cls):
        return OPIOSign({
            'input_post': Artifact(Path, sub_path=False), # .... $PATH_TO_ARTIFACTS/input_post, from the **runcal** step
            'input_all': Artifact(Path), # path to work_dir, e.g., $PATH_TO_ARTIFACTS/input_all/tmp/simple, from the **make** step
            'prop_param': dict,
            'inter_param': dict,
            'task_names': List[str], # e.g. [confs/std-bcc/msd-00/task.000001]
            'path_to_prop': str # e.g., confs/std-bcc/msd-00
        })

    @classmethod
    def get_output_sign(cls):
        return OPIOSign({
            'output_post': Artifact(Path)
        })

    @OP.exec_sign_check
    def execute(self, op_in: OPIO) -> OPIO:
        from ..core.common_prop import make_property_instance
        cwd = os.getcwd()
        print(cwd)
        print(op_in)
        input_post = op_in["input_post"]
        input_all = op_in["input_all"]
        prop_param = op_in["prop_param"]
        inter_param = op_in["inter_param"]
        task_names = op_in["task_names"]
        path_to_prop = op_in["path_to_prop"]
        calculator = inter_param["type"]
        copy_dir_list_input = [path_to_prop.split('/')[0]]
        os.chdir(input_all)
        copy_dir_list = []
        for ii in copy_dir_list_input:
            copy_dir_list.extend(glob.glob(ii))

        # find path of finished tasks
        os.chdir(op_in['input_post'])
        src_path = recursive_search(copy_dir_list) # results from run_op
        if not src_path:
            raise RuntimeError(f'Fail to find input work path after slices!')

        if calculator in ['vasp', 'abacus']:
            os.chdir(input_post)
            for ii in task_names:
                shutil.copytree(os.path.join(ii, "backward_dir"), ii, dirs_exist_ok=True)
                shutil.rmtree(os.path.join(ii, "backward_dir"))
            os.chdir(input_all)
            shutil.copytree(input_post, './', dirs_exist_ok=True) # copy calculation result from run_op
        else:
            os.chdir(input_all)
            #src_path = str(input_post) + str(local_path)
            shutil.copytree(src_path, './', dirs_exist_ok=True)

        if ("cal_setting" in prop_param
                and "overwrite_interaction" in prop_param["cal_setting"]):
            inter_param = prop_param["cal_setting"]["overwrite_interaction"]

        # cwd: XXX/input_all
        abs_path_to_prop = Path.cwd() / path_to_prop
        print(abs_path_to_prop)

        prop = make_property_instance(prop_param, inter_param)
        prop.compute(
            os.path.join(abs_path_to_prop, "result.json"),
            os.path.join(abs_path_to_prop, "result.out"),
            abs_path_to_prop,
        )
        # remove potential files in each md task
        os.chdir(abs_path_to_prop)
        cmd = "for kk in task.*; do cd $kk; rm *.pb; cd ..; done"
        subprocess.call(cmd, shell=True)

        os.chdir(cwd) # workdir
        out_path = Path(cwd) / 'retrieve_pool'
        os.mkdir(out_path)
        shutil.copytree(input_all / path_to_prop,
                        out_path / path_to_prop, dirs_exist_ok=True)# not sure why...

        op_out = OPIO({
            'output_post': abs_path_to_prop
        })
        return op_out

