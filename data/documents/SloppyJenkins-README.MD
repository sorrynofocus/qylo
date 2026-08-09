##  Sloppy Jenkins 
Safety: safe

### Local Jenkins Docker Container development box

### Purpose: To have a local jenkins instance; to develop shared libraries, debug, and work with internals. All this glory without the need to hit a production server.

- 🌱 Run jenkins and learn internals 
- ✍️ Write your own plugins... and blow it up, safely, in the container!

## Project stats:
- Linux Debian GNU/Linux 12 (bookworm)
- OpenJDK Runtime Environment Temurin-17.0.12+7 (build 17.0.12+7)
- Jenkins 2.470

## Build instructions

The project's source will do *everything* for you. At least, *try to*. 

The project will:

- Build the docker image
- Configure jenkins
- Install recommended plugins (see /plugins/pugins.txt)
- Set up an admin account (see /init-scripts/*)
- Get you started with a Docker container with a local Jenkins instance. This is enough to get a local server up and running with persistent server data.

### Prerequisites

1. You'll need `internet access`.

2. `Command prompt` (or ⚡Windows Terminal ⚡).

3. `Docker for Desktop for Windows`. This project was constructed as a linux image/container. Docker Desktop install is easy to install.

        Once Docker is setup, we will need to switch to Linux containers to use this project. 
        You can do this via right clicking on the white docker whale icon and choose 
        "Switch to Linux containers".

        OR

        At the command prompt, and enter:
        "c:\Program Files\Docker\Docker\dockercli" -SwitchLinuxEngine

        Note: You can later switch back to Windows containers via UI or 
        "c:\Program Files\Docker\Docker\dockercli" -SwitchWindowsEngine

### Build the initial Docker image
1. Once you've switched to Linux containers and downloaded this project's source files, enter the projects' directory and drop to a command prompt. 

        For example: If you copied the project's source to C:\docker-dynamic-jenkins-work, 
        switch to this directory by typing:

        cd C:\docker-dynamic-jenkins-work

2. Type: **build-docker-jenkins-cont.bat**

    Get coffee, or tea. Build time: ~15 minutes if never built, 3 minutes if previous build exist. Jenkins docker image will be completed shortly. 

3. Once **success** build is complete, type `restartjenkins`<BR>

    > You'll witness feed back, something similar to this:

    > c:\docker-dynamic-jenkins-work>f256d1fd1e62d8648cebb94cef09ec3b52b754b05940f67c1c6955871246b664
    This means a container has started. You can validate this by typing *docker ps* and validating *local_dev_jenkins_host* is running.
<BR>
<BR>
If NOT success, then examine the README files in the subfolders to help troubleshoot. Typical issue appear in the plugin folders. There's good documentation to debug the container. 

Note: Also, it may take some time to bring up the Jenkins server. It may appear the server is not running. Wait until you see the familiar message:

```
Please wait while Jenkins is getting ready to work ...
Your browser will reload automatically when Jenkins is ready.
```

4. In your browser migrate to: http://localhost:8787/  (please be patient. Jenkins is starting...)
<BR>
NOTE: Jenkins admin user/password is *admin/password*


Jenkins is ready!

NOTE: Don't close your command prompt or the alias `restartjenkins` will disappear. You'll need this in case you need to restart the Jenkins container when modifying files requiring a restart. IF you cannot use the `restartjenkins` alias, then run the `dsetup.bat` to restore it. This will also destroy the container and restart, but Jenkins data will not be deleted.


### Revisting the Jenkins instance from the container.

Once the image has been built, you can run the container at any time to ready the Jenkins instance. If you followed the instructions above, Jenkins will be setup and ready to run. If you closed down the container, or perhaps rebooted the Jenkins instance, you can easily run the instance again because you have a working image to run a new container.
Because the data is persistent, your Jenkins instance will retain the previous configuration. To revisit your Jenkins instance at a later time, you do so by these easy instructions:

1. Open a command prompt.

2. Move to this project's directory (where this project lives)

3. Type **dsetup.bat**
<BR>
    > If your Jenkins container is currently running, there's no need for step 4. Skip to step 5!

4. Type **restartjenkins**
    > You'll witness feed back, something similar to this:

    > c:\docker-dynamic-jenkins-work>f256d1fd1e62d8648cebb94cef09ec3b52b754b05940f67c1c6955871246b664
    This means a container has started. You can validate this by typing *docker ps* and validating *local_dev_jenkins_host* is running.
<BR>
<BR>
If NOT success, then examine the README files in the subfolders to help troubleshoot.

5. In your browser migrate to: http://localhost:8787/  (please be patient. Jenkins is starting...)
<BR>
NOTE: Jenkins admin user/password is `admin/password`

6. Jenkins is ready!


### ...Final word

- While Jenkins is running:
    - All data is persisted in the location `C:\MNT\docker\jenkins\jenkins_home` 
    - If you need to restart Jenkins, simply type `restartjenkins` at the command prompt you've left open.

- If need access to the Jenkins container, type:
    
    ```
    docker exec -it local_dev_jenkins /bin/bash
    ```


- To end your Jenkins container experience, type: 

    ```
    docker kill local_dev_jenkins
    ```


