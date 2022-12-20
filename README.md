# Magic-Garage
Python3 application that automatically opens a MyQ equipped garage door when one of your Teslas approaches and closes the door when your Tesla leaves. The current logic only supports a single vehicle and single garage door.

NOTE: As of Decemeber 2022, Tesla has released this exact functionality in their latest vehicle software update. However, there is a cost on the MyQ-side associated with using it. 


To Run Locally:
- Run the setup.sh script to install the required python modules
- Run the script with the Tesla and MyQ credentials as command line parameters:
    - ``>python3 magic_garage.py tesla_email tesla_password myq_email myq_password ``
