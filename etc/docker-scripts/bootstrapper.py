#
# Copyright 2018-2020 IBM Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import glob
import os
import subprocess
import sys

from packaging import version

# Inputs and Outputs separator character.  If updated,
# same-named variable in _notebook_op.py must be updated!
INOUT_SEPARATOR= ';'


def package_install():

    elyra_package_list = package_list_to_dict("requirements-elyra.txt")
    current_package_list = package_list_to_dict("requirements-current.txt")
    to_install_list = []

    for package, ver in elyra_package_list.items():
        if package in current_package_list:
            if "git+" in current_package_list[package]:
                print("WARNING: Source package %s found already installed from %s. This may "
                      "conflict with the required version: %s . Skipping..." %
                      (package, current_package_list[package], ver))
            elif isinstance(version.parse(current_package_list[package]), version.LegacyVersion):
                print("WARNING: Package %s found with unsupported Legacy version "
                      "scheme %s already installed. Skipping..." %
                      (package, current_package_list[package]))
            elif version.parse(ver) > version.parse(current_package_list[package]):
                print("Updating %s package from version %s to %s..." % (package, current_package_list[package], ver))
                to_install_list.append(package+'=='+ver)
            elif version.parse(ver) < version.parse(current_package_list[package]):
                print("Newer %s package with version %s already installed. Skipping..." %
                      (package, current_package_list[package]))
        else:
            print("Package not found. Installing %s package with version %s..." % (package, ver))
            to_install_list.append(package+'=='+ver)

    if to_install_list:
        if input_params['user-volume-path']:
            to_install_list.insert(0, '--target=' + input_params['user-volume-path'])
        subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + to_install_list)


def package_list_to_dict(filename):
    package_dict = {}
    with open(filename) as fh:
        for line in fh:
            if line[0] != '#':
                if " @ " in line:
                    package_name, package_version = line.strip('\n').split(sep=" @ ")
                elif "===" in line:
                    package_name, package_version = line.strip('\n').split(sep="===")
                else:
                    package_name, package_version = line.strip('\n').split(sep="==")

                package_dict[package_name] = package_version

    return package_dict


def parse_arguments(args):
    import argparse

    print("Parsing Arguments.....")
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--cos-endpoint', dest="cos-endpoint", help='Cloud object storage endpoint', required=True)
    parser.add_argument('-b', '--cos-bucket', dest="cos-bucket", help='Cloud object storage bucket to use', required=True)
    parser.add_argument('-d', '--cos-directory', dest="cos-directory", help='Working directory in cloud object storage bucket to use', required=True)
    parser.add_argument('-t', '--cos-dependencies-archive', dest="cos-dependencies-archive", help='Archive containing notebook and dependency artifacts', required=True)
    parser.add_argument('-n', '--notebook', dest="notebook", help='Notebook to execute', required=True)
    parser.add_argument('-o', '--outputs', dest="outputs", help='Files to output to object store', required=False)
    parser.add_argument('-i', '--inputs', dest="inputs", help='Files to pull in from parent node', required=False)
    parser.add_argument('-p', '--user-volume-path', dest="user-volume-path", help='Directory in Volume to install python libraries into', required=False)
    parsed_args = vars(parser.parse_args(args))

    return parsed_args


def convert_notebook_to_html(notebook_file, html_file):
    """
    Function to convert a Jupyter notebook file (.ipynb) into an html file

    :param notebook_file: object storage client
    :param html_file: name of what the html output file should be
    :return: html_file: the converted notebook in html format
    """
    import nbconvert
    import nbformat

    print("Converting from ipynb to html....")
    nb = nbformat.read(notebook_file, as_version=4)
    html_exporter = nbconvert.HTMLExporter()
    data, resources = html_exporter.from_notebook_node(nb)
    with open(html_file, "w") as f:
        f.write(data)
        f.close()

    return html_file


def get_object_storage_filename(filename):
    """
    Function to pre-pend cloud storage working dir to file name

    :param filename: the local file
    :return: the full path of the object storage file
    """
    return os.path.join(input_params['cos-directory'], filename)


def get_file_from_object_storage(client, bucket_name, file_to_get):
    """
    Utility function to get files from an object storage

    :param client: object storage client
    :param bucket_name: bucket where files are located
    :param file_to_get: filename
    """

    print('Get file {} from bucket {}'.format(file_to_get, bucket_name))
    object_to_get = get_object_storage_filename(file_to_get)

    client.fget_object(bucket_name=bucket_name,
                       object_name=object_to_get,
                       file_path=file_to_get)


def put_file_to_object_storage(client, bucket_name, file_to_upload, object_name=None):
    """
    Utility function to put files into an object storage
    :param client: object storage client
    :param bucket_name: bucket where files are located
    :param file_to_upload: filename
    :param object_name: remote filename (used to rename)
    """

    object_to_upload = object_name
    if not object_to_upload:
        object_to_upload = file_to_upload

    print('Uploading file {} as {} to bucket {}'.format(file_to_upload, object_to_upload, bucket_name))

    object_to_upload = get_object_storage_filename(object_to_upload)

    client.fput_object(bucket_name=bucket_name,
                       object_name=object_to_upload,
                       file_path=file_to_upload)


def has_wildcard(filename):
    wildcards = ['*', '?']
    return bool(any(c in filename for c in wildcards))


def process_output_file(cos_client, bucket, output_file):
    """Puts the file to object storage.  Handles wildcards and directories. """

    matched_files = [output_file]
    if has_wildcard(output_file):  # explode the wildcarded file
        matched_files = glob.glob(output_file)

    for matched_file in matched_files:
        if os.path.isdir(matched_file):
            for file in os.listdir(matched_file):
                process_output_file(cos_client, bucket, os.path.join(matched_file, file))
        else:
            put_file_to_object_storage(cos_client, bucket, matched_file)


def main():
    global input_params
    input_params = parse_arguments(sys.argv[1:])

    package_install()
    subprocess.check_call([sys.executable, '-m', 'pip', 'freeze'])

    import minio
    import papermill

    from urllib.parse import urlparse

    print("Package Installation Complete.....")

    cos_endpoint = urlparse(input_params['cos-endpoint'])
    cos_client = minio.Minio(cos_endpoint.netloc,
                             access_key=os.getenv('AWS_ACCESS_KEY_ID'),
                             secret_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                             secure=cos_endpoint.scheme == 'https')

    get_file_from_object_storage(cos_client, input_params['cos-bucket'], input_params['cos-dependencies-archive'])

    print('Processing dependencies........')
    if 'inputs' in input_params and input_params['inputs']:
        input_list = input_params['inputs'].split(INOUT_SEPARATOR)
        for file in input_list:
            get_file_from_object_storage(cos_client, input_params['cos-bucket'], file.strip())

    print("TAR Archive pulled from Object Storage.")
    print("Unpacking........")
    subprocess.call(['tar', '-zxvf', input_params["cos-dependencies-archive"]])
    print("Unpacking Complete.")

    # Execute notebook
    notebook = os.path.basename(input_params['notebook'])
    notebook_name = notebook.replace('.ipynb', '')
    notebook_output = notebook_name + '-output.ipynb'
    notebook_html = notebook_name + '.html'

    print("Executing notebook through Papermill: {} ==> {}"
          .format(notebook, notebook_output))

    try:
        assert os.path.isfile(notebook), "File '{}' is invalid".format(notebook)
        papermill.execute_notebook(
            notebook,
            notebook_output,
            kernel_name="python3"
            # parameters=
        )

        convert_notebook_to_html(notebook_output, notebook_html)
        print("Uploading Result Notebook back to Object Storage")
        put_file_to_object_storage(cos_client, input_params['cos-bucket'], notebook_output, notebook)
        put_file_to_object_storage(cos_client, input_params['cos-bucket'], notebook_html)

        print('Processing outputs........')
        if 'outputs' in input_params and input_params['outputs']:
            output_list = input_params['outputs'].split(INOUT_SEPARATOR)
            for file in output_list:
                process_output_file(cos_client, input_params['cos-bucket'], file.strip())
    except:
        # log in case of errors
        print("Unexpected error:", sys.exc_info()[0])
        convert_notebook_to_html(notebook_output, notebook_html)

        print("Uploading Errored Notebook back to Object Storage")
        put_file_to_object_storage(cos_client, input_params['cos-bucket'], notebook_output, notebook)
        put_file_to_object_storage(cos_client, input_params['cos-bucket'], notebook_html)

        raise

    print("Upload Complete.")


if __name__ == '__main__':
    input_params = {}
    main()
