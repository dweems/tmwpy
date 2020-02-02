#!/usr/bin/python
"""
Copyright 2011, Dipesh Amin <yaypunkrock@gmail.com>
Copyright 2011, Stefan Beller <stefanbeller@googlemail.com>

This file is part of tradey, a trading bot in The Mana World
see www.themanaworld.org

This program is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation; either version 2 of the License, or (at your option)
any later version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.

Additionally to the GPL, you are *strongly* encouraged to share any modifications
you do on these sources.
"""

import logging
import logging.handlers
import socket
import sys
import time
import string

try:
    import config
except:
    print "no config file found. please move config.py.template to config.py and edit to your needs!"
    sys.exit(0);

from being import *
from net.packet import *
from net.protocol import *
from net.packet_out import *
from player import *
import utils
from onlineusers import SqliteDbManager

ItemDB = utils.ItemDB()
player_node = Player('')
beingManager = BeingManager()
ItemLog = utils.ItemLog()
logger = logging.getLogger('ManaLogger')

def main():
    # Use rotating log files.
    log_handler = logging.handlers.RotatingFileHandler('data/logs/activity.log', maxBytes=1048576*3, backupCount=5)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)
    logger.addHandler(logging.StreamHandler())

    logger.info("Bot Started.")

    account = config.account
    password = config.password
    character = config.character

    login = socket.socket()
    login.connect((config.server, config.port))
    logger.info("Login connected")

    login_packet = PacketOut(0x0064)
    login_packet.write_int32(6) # <= CLIENT VERSION
    login_packet.write_string(account, 24)
    login_packet.write_string(password, 24)
    login_packet.write_int8(0x03); # <= FLAGS
    login.sendall(str(login_packet))

    pb = PacketBuffer()
    id1 = accid = id2 = 0
    charip = ""
    charport = 0
    # Login server packet loop.
    while True:
        data = login.recv(1500)
        if not data:
            break
        pb.feed(data)
        for packet in pb:
            if packet.is_type(SMSG_LOGIN_DATA): # login succeeded
                packet.skip(2)
                id1 = packet.read_int32()
                accid = packet.read_int32()
                id2 = packet.read_int32()
                packet.skip(30)
                player_node.sex = packet.read_int8()
                charip = utils.parse_ip(packet.read_int32())
                charport = packet.read_int16()
                login.close()
                break
        if charip:
            break

    assert charport

    if charip == "127.0.0.1" and config.server != "127.0.0.1":
        charip = config.server

    char = socket.socket()
    char.connect((charip, charport))
    logger.info("Char connected")
    char_serv_packet = PacketOut(CMSG_CHAR_SERVER_CONNECT)
    char_serv_packet.write_int32(accid)
    char_serv_packet.write_int32(id1)
    char_serv_packet.write_int32(id2)
    char_serv_packet.write_int16(1) # this should match MIN_CLIENT_VERSION in tmwa/src/char/char.hpp
    char_serv_packet.write_int8(player_node.sex)
    char.sendall(str(char_serv_packet))
    char.recv(4)

    pb = PacketBuffer()
    mapip = ""
    mapport = 0
    # Character Server Packet loop.
    while True:
        data = char.recv(1500)
        if not data:
            break
        pb.feed(data)
        for packet in pb:
            if packet.is_type(SMSG_CHAR_LOGIN):
                packet.skip(2)
                slots = packet.read_int16()
                packet.skip(18)
                count = (len(packet.data)-22) / 106
                for i in range(count):
                    player_node.id = packet.read_int32()
                    player_node.EXP = packet.read_int32()
                    player_node.MONEY = packet.read_int32()
                    packet.skip(62)
                    player_node.name = packet.read_string(24)
                    packet.skip(6)
                    slot = packet.read_int8()
                    packet.skip(1)
                    logger.info("Character information recieved:")
                    logger.info("Name: %s, Id: %s, EXP: %s, MONEY: %s", \
                    player_node.name, player_node.id, player_node.EXP, player_node.MONEY)
                    if slot == character:
                        break

                char_select_packet = PacketOut(CMSG_CHAR_SELECT)
                char_select_packet.write_int8(character)
                char.sendall(str(char_select_packet))

            elif packet.is_type(SMSG_CHAR_MAP_INFO):
                player_node.id = packet.read_int32()
                player_node.map = packet.read_string(16)
                mapip = utils.parse_ip(packet.read_int32())
                mapport = packet.read_int16()
                char.close()
                break
        if mapip:
            break

    assert mapport

    if mapip == "127.0.0.1" and charip != "127.0.0.1":
        mapip = charip

    beingManager.container[player_node.id] = Being(player_node.id, 42)
    mapserv = socket.socket()
    mapserv.connect((mapip, mapport))
    logger.info("Map connected")
    mapserv_login_packet = PacketOut(CMSG_MAP_SERVER_CONNECT)
    mapserv_login_packet.write_int32(accid)
    mapserv_login_packet.write_int32(player_node.id)
    mapserv_login_packet.write_int32(id1)
    mapserv_login_packet.write_int32(id2)
    mapserv_login_packet.write_int8(player_node.sex)
    mapserv.sendall(str(mapserv_login_packet))
    mapserv.recv(4)

    pb = PacketBuffer()

    # Map server packet loop
    print "Entering map packet loop\n";
    while True:
        data = mapserv.recv(2048)
        if not data:
            break
        pb.feed(data)

        for packet in pb:
            if packet.is_type(SMSG_MAP_LOGIN_SUCCESS): # connected
                logger.info("Map login success.")
                packet.skip(4)
                coord_data = packet.read_coord_dir()
                player_node.x = coord_data[0]
                player_node.y = coord_data[1]
                player_node.direction = coord_data[2]
                logger.info("Starting Postion: %s %s %s", player_node.map, player_node.x, player_node.y)
                mapserv.sendall(str(PacketOut(CMSG_MAP_LOADED))) # map loaded
                # A Thread to send a shop broadcast: also keeps the network active to prevent timeouts.

            elif packet.is_type(SMSG_PVP_SET):
                packet.skip(12)

            elif packet.is_type(SMSG_PVP_MAP_MODE):
                packet.skip(2)

            elif packet.is_type(SMSG_QUEST_SET_VAR):
                packet.skip(6)

            elif packet.is_type(SMSG_QUEST_PLAYER_VARS):
                nb = (packet.read_int16() - 4) / 6
                for loop in range(nb):
                    packet.skip(6)

            elif packet.is_type(SMSG_NPC_COMMAND):
                packet.skip(14)

            elif packet.is_type(SMSG_BEING_MOVE3):
                nb = (packet.read_int16() - 14) / 1
                packet.skip(10)
                for loop in range(nb):
                    packet.skip(1)

            elif packet.is_type(SMSG_MAP_MASK):
                packet.skip(8)

            elif packet.is_type(SMSG_MAP_MUSIC):
                nb = (packet.read_int16() - 4) / 1
                for loop in range(nb):
                    packet.skip(1)

            elif packet.is_type(SMSG_NPC_CHANGETITLE):
                nb = (packet.read_int16() - 10) / 1
                packet.skip(6)
                for loop in range(nb):
                    packet.skip(1)

            elif packet.is_type(SMSG_SCRIPT_MESSAGE):
                nb = (packet.read_int16() - 5) / 1
                packet.skip(1)
                for loop in range(nb):
                    packet.skip(1)

            elif packet.is_type(SMSG_PLAYER_CLIENT_COMMAND):
                nb = (packet.read_int16() - 4) / 1
                for loop in range(nb):
                    packet.skip(1)

            elif packet.is_type(SMSG_MAP_SET_TILES_TYPE):
                packet.skip(32)

            elif packet.is_type(SMSG_PLAYER_HP):
                packet.skip(8)

            elif packet.is_type(SMSG_PLAYER_HP_FULL):
                packet.skip(12)

            elif packet.is_type(SMSG_WHISPER):
                msg_len = packet.read_int16() - 26
                nick = packet.read_string(24)
                message = packet.read_raw_string(msg_len)
                # Clean up the logs.
                logger.info("Whisper: " + nick + ": " + message)

            elif packet.is_type(SMSG_PLAYER_STAT_UPDATE_1):
                stat_type = packet.read_int16()
                value = packet.read_int32()
                if stat_type == 0x0018:
                    logger.info("Weight changed from %s/%s to %s/%s", \
                    player_node.WEIGHT, player_node.MaxWEIGHT, value, player_node.MaxWEIGHT)
                    player_node.WEIGHT = value
                elif stat_type == 0x0019:
                    logger.info("Max Weight: %s", value)
                    player_node.MaxWEIGHT = value

            elif packet.is_type(SMSG_PLAYER_STAT_UPDATE_2):
                stat_type = packet.read_int16()
                value = packet.read_int32()
                if stat_type == 0x0014:
                    logger.info("Money Changed from %s, to %s", player_node.MONEY, value)
                    player_node.MONEY = value

            elif packet.is_type(SMSG_BEING_MOVE) or packet.is_type(SMSG_BEING_VISIBLE)\
            or packet.is_type(SMSG_PLAYER_MOVE) or packet.is_type(SMSG_PLAYER_UPDATE_1)\
            or packet.is_type(SMSG_PLAYER_UPDATE_2):
                being_id = packet.read_int32()
                packet.skip(8)
                job = packet.read_int16()
                if being_id not in beingManager.container:
                    if job == 0 and id >= 110000000 and (packet.is_type(SMSG_BEING_MOVE)\
                                                         or packet.is_type(SMSG_BEING_VISIBLE)):
                        continue
                    # Add the being to the BeingManager, and request name.
                    beingManager.container[being_id] = Being(being_id, job)
                    requestName = PacketOut(0x0094)
                    requestName.write_int32(being_id)
                    mapserv.sendall(str(requestName))

            elif packet.is_type(SMSG_BEING_NAME_RESPONSE):
                being_id = packet.read_int32()
                if being_id in beingManager.container:
                    beingManager.container[being_id].name = packet.read_string(24)

            elif packet.is_type(SMSG_BEING_REMOVE):
                being_id = packet.read_int32()
                if being_id in beingManager.container:
                    del beingManager.container[being_id]

            elif packet.is_type(SMSG_PLAYER_WARP):
                player_node.map = packet.read_string(16)
                player_node.x = packet.read_int16()
                player_node.y = packet.read_int16()
                logger.info("Player warped: %s %s %s", player_node.map, player_node.x, player_node.y)
                mapserv.sendall(str(PacketOut(CMSG_MAP_LOADED)))

            elif packet.is_type(SMSG_PLAYER_INVENTORY_ADD):
                item = Item()
                item.index = packet.read_int16() - inventory_offset
                item.amount = packet.read_int16()
                item.itemId = packet.read_int16()
                packet.skip(14)
                err = packet.read_int8()

                if err == 0:
                    if item.index in player_node.inventory:
                        player_node.inventory[item.index].amount += item.amount
                    else:
                        player_node.inventory[item.index] = item

                    logger.info("Picked up: %s, Amount: %s, Index: %s", ItemDB.getItem(item.itemId).name, str(item.amount), str(item.index))

            elif packet.is_type(SMSG_PLAYER_INVENTORY_REMOVE):
                index = packet.read_int16() - inventory_offset
                amount = packet.read_int16()

                logger.info("Remove item: %s, Amount: %s, Index: %s", ItemDB.getItem(player_node.inventory[index].itemId).name, str(amount), str(index))
                player_node.remove_item(index, amount)

            elif packet.is_type(SMSG_PLAYER_INVENTORY):
                player_node.inventory.clear() # Clear the inventory - incase of new index.
                packet.skip(2)
                number = (len(packet.data)-2) / 18
                for loop in range(number):
                    item = Item()
                    item.index = packet.read_int16() - inventory_offset
                    item.itemId = packet.read_int16()
                    packet.skip(2)
                    item.amount = packet.read_int16()
                    packet.skip(10)
                    player_node.inventory[item.index] = item

            elif packet.is_type(SMSG_PLAYER_EQUIPMENT):
                packet.read_int16()
                number = (len(packet.data)) / 20
                for loop in range(number):
                    item = Item()
                    item.index = packet.read_int16() - inventory_offset
                    item.itemId = packet.read_int16()
                    packet.skip(16)
                    item.amount = 1
                    player_node.inventory[item.index] = item

                logger.info("Inventory information received:")
                for item in player_node.inventory:
                    logger.info("Name: %s, Id: %s, Index: %s, Amount: %s.", \
                    ItemDB.getItem(player_node.inventory[item].itemId).name, \
                    player_node.inventory[item].itemId, item, player_node.inventory[item].amount)

                else:
                    logger.info("Inventory Check Passed.")

            elif packet.is_type(SMSG_TRADE_REQUEST):
                name = packet.read_string(24)
                logger.info("Trade request: " + name)
                mapserv.sendall(trade_respond(False))

            elif packet.is_type(SMSG_TRADE_RESPONSE):
                response = packet.read_int8()
                time.sleep(0.2)
                if response == 0:
                    logger.info("Trade response: Too far away.")
                    if trader_state.item:
                        mapserv.sendall(whisper(trader_state.item.player, "You are too far away."))
                    elif trader_state.money:
                        mapserv.sendall(whisper(trader_state.money, "You are too far away."))
                    trader_state.reset()

                elif response == 3:
                    logger.info("Trade response: Trade accepted.")
                    if trader_state.item:
                        if trader_state.item.get == 1: # add
                            mapserv.sendall(str(PacketOut(CMSG_TRADE_ADD_COMPLETE)))
                        elif trader_state.item.get == 0: # buy
                            if player_node.find_inventory_index(trader_state.item.id) != -10:
                                mapserv.sendall(trade_add_item(player_node.find_inventory_index(trader_state.item.id), trader_state.item.amount))
                                mapserv.sendall(str(PacketOut(CMSG_TRADE_ADD_COMPLETE)))
                                if trader_state.item.price == 0: # getback
                                    mapserv.sendall(str(PacketOut(CMSG_TRADE_OK)))
                                    trader_state.complete = 1
                            else:
                                mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                                logger.info("Trade response: Trade accepted (buy) - the item could not be added.")
                                mapserv.sendall(whisper(trader_state.item.player, "Sorry, a problem has occured."))

                    elif trader_state.money: # money
                        amount = int(user_tree.get_user(trader_state.money).get('money'))
                        mapserv.sendall(trade_add_item(0-inventory_offset, amount))
                        mapserv.sendall(str(PacketOut(CMSG_TRADE_ADD_COMPLETE)))
                        mapserv.sendall(str(PacketOut(CMSG_TRADE_OK)))

                else:
                    logger.info("Trade response: Trade cancelled")

            elif packet.is_type(SMSG_TRADE_ITEM_ADD):
                amount = packet.read_int32()
                item_id = packet.read_int16()
                if trader_state.item and trader_state.money == 0:
                    if  trader_state.item.get == 1: # add
                        if amount == trader_state.item.amount and item_id == trader_state.item.id:
                            trader_state.complete = 1
                            mapserv.sendall(str(PacketOut(CMSG_TRADE_OK)))
                        elif item_id == 0 and amount > 0:
                            mapserv.sendall(whisper(trader_state.item.player, "Why are you adding money?!?!"))
                            mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                        else:
                            mapserv.sendall(whisper(trader_state.item.player, "Please check the correct item or quantity has been added."))
                            mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

                    elif trader_state.item.get == 0: # buy
                        if item_id == 0 and amount == trader_state.item.price * trader_state.item.amount:
                            mapserv.sendall(str(PacketOut(CMSG_TRADE_OK)))
                            trader_state.complete = 1
                        elif item_id == 0 and amount != trader_state.item.price * trader_state.item.amount:
                            trader_state.complete = 0
                        else:
                            mapserv.sendall(whisper(trader_state.item.player, "Don't give me your itenz."))
                            mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

                elif trader_state.money: # money
                    mapserv.sendall(whisper(trader_state.money, "Don't give me your itenz."))
                    mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

                logger.info("Trade item add: ItemId:%s Amount:%s", item_id, amount)
                # Note item_id = 0 is money

            elif packet.is_type(SMSG_TRADE_ITEM_ADD_RESPONSE):
                index = packet.read_int16() - inventory_offset
                amount = packet.read_int16()
                response = packet.read_int8()

                if response == 0:
                    logger.info("Trade item add response: Successfully added item.")
                    if trader_state.item:
                        if trader_state.item.get == 0 and index != 0-inventory_offset: # Make sure the correct item is given!
                            # index & amount are Always 0
                            if player_node.inventory[index].itemId != trader_state.item.id or \
                                amount != trader_state.item.amount:
                                logger.info("Index: %s" % index)
                                logger.info("P.ItemId: %s" % player_node.inventory[index].itemId)
                                logger.info("T.ItemId: %s" % trader_state.item.id)
                                logger.info("P.Amount: %s" % amount)
                                logger.info("T.Amount: %s" % trader_state.item.amount)
                                #mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

                    # If Trade item add successful - Remove the item from the inventory state.
                    if index != 0: # If it's not money
                        logger.info("Remove item: %s, Amount: %s, Index: %s", ItemDB.getItem(player_node.inventory[index].itemId).name, str(amount),str(index))
                        player_node.remove_item(index, amount)
                    else:
                        # The money amount isn't actually sent by the server - odd?!?!?.
                        if trader_state.money:
                            logger.info("Trade: Money Added.")
                            trader_state.complete = 1

                elif response == 1:
                    logger.info("Trade item add response: Failed - player overweight.")
                    mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                    if trader_state.item:
                        mapserv.sendall(whisper(trader_state.item.player, "You are carrying too much weight. Unload and try again."))
                elif response == 2:
                    if trader_state.item:
                        mapserv.sendall(whisper(trader_state.item.player, "You have no free slots."))
                    logger.info("Trade item add response: Failed - No free slots.")
                    mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                else:
                    logger.info("Trade item add response: Failed - unknown reason.")
                    mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                    if trader_state.item:
                        mapserv.sendall(whisper(trader_state.item.player, "Sorry, a problem has occured."))

            elif packet.is_type(SMSG_TRADE_OK):
                is_ok = packet.read_int8() # 0 is ok from self, and 1 is ok from other
                if is_ok == 0:
                    logger.info("Trade OK: Self.")
                else:
                    if trader_state.complete:
                        mapserv.sendall(str(PacketOut(CMSG_TRADE_OK)))
                    else:
                        mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                        if trader_state.item:
                            mapserv.sendall(whisper(trader_state.item.player, "Trade Cancelled: Please check the traded items or money."))

                    logger.info("Trade Ok: Partner.")

            elif packet.is_type(SMSG_TRADE_CANCEL):
                trader_state.reset()
                logger.info("Trade Cancel.")

            elif packet.is_type(SMSG_TRADE_COMPLETE):
                commitMessage=""
                # The sale_tree is only ammended after a complete trade packet.
                if trader_state.item and trader_state.money == 0:
                    if trader_state.item.get == 1: # !add
                        sale_tree.add_item(trader_state.item.player, trader_state.item.id, trader_state.item.amount, trader_state.item.price)
                        user_tree.get_user(trader_state.item.player).set('used_stalls', \
                            str(int(user_tree.get_user(trader_state.item.player).get('used_stalls')) + 1))
                        user_tree.get_user(trader_state.item.player).set('last_use', str(time.time()))
                        commitMessage = "Add"

                    elif trader_state.item.get == 0: # !buy \ !getback
                        seller = sale_tree.get_uid(trader_state.item.uid).get('name')
                        item = sale_tree.get_uid(trader_state.item.uid)
                        current_amount = int(item.get("amount"))
                        sale_tree.get_uid(trader_state.item.uid).set("amount", str(current_amount - trader_state.item.amount))
                        if int(item.get("amount")) == 0:
                            user_tree.get_user(sale_tree.get_uid(trader_state.item.uid).get('name')).set('used_stalls', \
                                str(int(user_tree.get_user(sale_tree.get_uid(trader_state.item.uid).get('name')).get('used_stalls'))-1))
                            sale_tree.remove_item_uid(trader_state.item.uid)

                        current_money = int(user_tree.get_user(seller).get("money"))
                        user_tree.get_user(seller).set("money", str(current_money + trader_state.item.price * trader_state.item.amount))

                        if trader_state.item.price * trader_state.item.amount != 0:
                            ItemLog.add_item(int(item.get('itemId')), trader_state.item.amount, trader_state.item.price * trader_state.item.amount, item.get('name'))
                        commitMessage = "Buy or Getback"

                elif trader_state.money and trader_state.item == 0: # !money
                    user_tree.get_user(trader_state.money).set('money', str(0))
                    commitMessage = "Money"

                sale_tree.save()
                user_tree.save()
                tradey.saveData(commitMessage)

                trader_state.reset()
                logger.info("Trade Complete.")

                errorOccured = player_node.check_inventory(user_tree, sale_tree)
                if errorOccured:
                    logger.info(errorOccured)
                    shop_broadcaster.stop()
                    sys.exit(1)
            else:
                pass

    # On Disconnect/Exit
    logger.info("Server disconnect.")
    mapserv.close()

if __name__ == '__main__':
    main()
