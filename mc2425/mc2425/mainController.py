import rclpy
import os
from rclpy.node import Node
from std_msgs.msg import Int32
from mc2425_msgs.msg import AddPart
from mc2425_msgs.msg import PnPRemoval
from mc2425_msgs.srv import FileTransfer
from std_msgs.msg import String
from std_srvs.srv import SetBool
from mc2425.variables import GCODE_PATH, SLOT_NUMBER, HEIGHT


from mc2425.shelfClass import partsShelf
from mc2425.gcode import gcode
from mc2425.queueInteraction import download_gcode, checkStatus
from mc2425.discordNotification import send_notification


class MainController(Node):
    def __init__(self):
        super().__init__("mainController")
        self.addSubscription = self.create_subscription(
            AddPart, "finishedPrint", self.addPart_callback, 10
        )
        self.addSubscription  # prevent unused variable warning
        self.shelfCheckSub = self.create_subscription(
            Int32, "shelfCheck", self.shelfCheck_callback, 10
        )
        self.shelfCheckSub  # prevent unused variable warning
        self.removePartSub = self.create_subscription(
            Int32, "removePart", self.removePart_callback, 10
        )
        self.removePartSub  # prevent unused variable warning
        self.clearShelfSub = self.create_subscription(
            String, "clearShelf", self.clearShelf_callback, 10
        )
        self.clearShelfSub  # prevent unused variable warning
        self.pnpRemoverPub = self.create_publisher(PnPRemoval, "pnpRemover", 10)
        self.addPartFail = self.create_publisher(AddPart, "addPartFail", 10)

        self.requestGcodeService = self.create_service(
            FileTransfer, "requestGcode", self.handle_gcode_request
        )
        
        self.onlineService = self.create_service(SetBool, "checkOnline", self.check_online_callback)

        self.printerParts = []

        self.shelf = partsShelf(SLOT_NUMBER, HEIGHT)
        self.get_logger().info(f"Main Controller initialized")

    def determineRemoval(self):
        """
        TODO
        :return: Boolean on whether it should be removed from plate
        """
        return False

    def addPart(self, name, author, height):
        """
        Adds a part to the shelf and tells the printer to go to a specific slot
        :param data: List of data from a TCP socket request
        :return: String to send back to client
        """
        part = gcode(name, author, float(height))
        confirm, slot = self.shelf.addPart(part)
        if confirm:
            return f"Part added successfully in slot {slot}", slot
        else:
            return "Part not added, skipping...", -1

    def handle_gcode_request(self, request, response):
        """
        Handles G-code file transfer requests.
        """
        filename = download_gcode()
        if filename == -1:
            response.success = False
            response.message = "No files available for download."
            self.get_logger().info(response.message)
            return response

        response.filename = filename
        self.get_logger().info(f"Received file request for: {filename}")

        try:
            # Locate the requested file
            gcode_path = os.path.join(GCODE_PATH, filename)
            with open(gcode_path, "r") as file:
                response.filedata = file.read()
            response.success = True
            response.message = f"File {filename} successfully transferred."
            self.get_logger().info(response.message)
            os.remove(gcode_path)
        except FileNotFoundError:
            response.success = False
            response.message = f"File {filename} not found."
            self.get_logger().error(response.message)
        except Exception as e:
            response.success = False
            response.message = f"Error reading file: {str(e)}"
            self.get_logger().error(response.message)

        return response

    def addPart_callback(self, msg):
        self.get_logger().info(
            f"Received: {msg.printer_id} {msg.print_height} {msg.part_name} {msg.author}"
        )
        message, slot = self.addPart(msg.part_name, msg.author, msg.print_height)
        self.get_logger().info(message)
        if slot != -1:
            pnpRemover_msg = PnPRemoval()
            pnpRemover_msg.print_removal = self.determineRemoval()
            pnpRemover_msg.print_id = msg.printer_id
            pnpRemover_msg.shelf_num = slot
            self.pnpRemoverPub.publish(pnpRemover_msg)
            self.get_logger().info(
                f"Publishing: Removal: {pnpRemover_msg.print_removal}, Printer Number: {pnpRemover_msg.print_id}, Slot Number: {pnpRemover_msg.shelf_num}"
            )
            send_notification(
                f"<@{msg.author}> Part: **{msg.part_name}** is ready for pick up in slot: **{slot}**"
            )
            try:
                self.printerParts.remove(msg.part_name)
            except ValueError:
                self.get_logger().info("Part not found in printerParts, ignoring...")
                
        else:
            self.addPartFail.publish(msg)
            self.get_logger().info("Publishing: Part not added")
            if msg.part_name not in self.printerParts:
                send_notification(
                    f"<@{msg.author}> Shelf is full, part: **{msg.part_name}** is available for pick up on printer: **{msg.printer_id}**"
                )
                self.printerParts.append(msg.part_name)
                
    def check_online_callback(self, request, response):
        queue_is_online = checkStatus()  # Replace with actual logic

        response.success = queue_is_online
        response.message = "Queue is online" if queue_is_online else "Queue is offline"
        self.get_logger().info(response.message)
        return response

    def clearShelf_callback(self, msg):
        self.get_logger().info(f"Received: {msg.data}")
        self.shelf.clearShelf()
        self.get_logger().info("Shelf cleared")

    def shelfCheck_callback(self, msg):
        shelfNum = msg.data
        self.get_logger().info(f"Received: {shelfNum}")
        part = self.shelf.shelfChecker(shelfNum)
        if part is not None:
            self.get_logger().info(f"{part} found at #{shelfNum}")
        else:
            self.get_logger().info(f"No part found at #{shelfNum}")

    def removePart_callback(self, msg):
        shelfNum = msg.data
        self.get_logger().info(f"Received: {shelfNum}")
        remove = self.shelf.removePart(shelfNum)
        if remove:
            self.get_logger().info(f"Successful remove at #{shelfNum}")
        else:
            self.get_logger().info(f"No part found at #{shelfNum}")


def main(args=None):
    rclpy.init(args=args)
    Main_Controller = MainController()
    rclpy.spin(Main_Controller)
    Main_Controller.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
