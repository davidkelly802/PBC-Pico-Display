# Micropython specifically for Pi Pico
Written for Pi Pico 2W
Pulls image created by the render-app container
------------------------------------------------
The application merely fetches the image and refreshes the display about every 15 minutes

NOTE: due to bug in the current micropython version we can't go into deep sleep which impacts battery life. 
