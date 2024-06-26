import cv2
import mediapipe as mp
import numpy as np
from time import sleep
import time
from ultralytics import YOLO
from mediapipePose import mediapipePose
from ArUcoMarker import ArUco
from new_class import FaceDetector
import socket
import struct
import pickle
import sys
import mysql.connector
import io
from PIL import Image
import os
import threading
import queue


class MainServer:
    def __init__(self):
        self.InitMysql()
        self.InitFace()
        self.InitPose()
        self.InitFashion()
        self.InitCombine()
        self.InitQueue()
        self.InitTCP()

        # Thread define
        self.exitFlag = threading.Event()
        self.tcpReceiveThread = threading.Thread(target=self.tcpReceive, args=(self.client_socket_1, self.originFrameQueue1))
        self.tcpReceiveThread.start()

        self.deeplearnThread = threading.Thread(target=self.deeplearn, args=(self.originFrameQueue1, self.originFrameQueue2, self.originFrameQueue3, self.faceQueue, self.poseQueue, self.fashionQueue))
        self.deeplearnThread.start()

        self.tcpSendThread = threading.Thread(target=self.tcpSend, args=(self.faceQueue, self.poseQueue, self.fashionQueue))
        self.tcpSendThread.start()
        print("start Thread")

    def InitTCP(self):
        HOST = "192.168.0.40" # server pc IP
        PORT1 = 9020  # 원본 프레임 수신용 포트
        PORT2 = 9021  # 처리 결과 GUI로 전송용 포트
        PORT3 = 9022  # GUI Result

        # 서버 소켓 생성 및 원본 프레임 수신용 포트에 바인딩
        # receive origin camera frame from Raspberry
        self.server_socket_1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket_1.bind((HOST, PORT1))
        self.server_socket_1.listen(5)

        # 서버 소켓 생성 및 처리 결과 전송용 포트에 바인딩
        # send deeplearning result frame to GUI
        self.server_socket_2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket_2.bind((HOST, PORT2))
        self.server_socket_2.listen(5)

        # GUI
        # bidirectional signal communication from GUI
        self.server_socket_3 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket_3.bind((HOST, PORT3))
        self.server_socket_3.listen(1)

        print("waiting Cam connection")
        self.client_socket_1, addr1 = self.server_socket_1.accept() # Raspberry
        print(f"연결 수락됨 from {addr1}")
        print("waiting GUI frame connection")
        self.client_socket_2, addr2 = self.server_socket_2.accept() # GUI Frame
        print(f"연결 수락됨 from {addr2}")
        print("waiting GUI signal connection")
        self.client_socket_3, addr3 = self.server_socket_3.accept() # GUI signal
        print(f"연결 수락됨 from {addr3}")

    def InitMysql(self):
        # DB Address
        connection = mysql.connector.connect(
                host="192.168.0.40",
                user="YJS",
                password="1234",
                database="findperson"
            )
        # 저장할 이미지 폴더의 경로를 지정합니다.
        self.new_images = []
        self.new_names = []

        cursor = connection.cursor()
        query = "SELECT NAME FROM PERSON"
        cursor.execute(query)
        data = cursor.fetchall()    
        self.new_names = [name[0] for name in data if isinstance(name[0], str)]
        print(self.new_names)

        cursor = connection.cursor()
        query = "SELECT PICTURE FROM PERSON"
        cursor.execute(query)
        data = cursor.fetchall()  

        # 현재 스크립트의 경로를 얻습니다.
        current_dir = os.path.dirname(os.path.abspath(__file__))

        
        save_dir = os.path.join(current_dir, 'src')
        for i, image_data in enumerate(data):
            image_binary = image_data[0]
            image_stream = io.BytesIO(image_binary)
            image = Image.open(image_stream)
            image_path = os.path.join(save_dir, f"image_{self.new_names[i]}.png")
            image.save(image_path)
            self.new_images.append(f'src/image_{self.new_names[i]}.png')
        print(self.new_images)
        print("이미지 저장이 완료되었습니다.")
    
    def InitFace(self):
        self.faceInst = FaceDetector(self.new_images, self.new_names)

    def InitPose(self):
        self.poseInst = mediapipePose()
        self.ArUcoInst = ArUco()
        self.ratio = 0.92 # 0.73

    def InitFashion(self):
        self.model = YOLO('yolov8n.pt')

    def InitCombine(self):
        combined_frame_width = 1280
        combined_frame_height = 960
        self.combined_frame = np.zeros((combined_frame_height, combined_frame_width, 3), dtype=np.uint8)

    def InitQueue(self):
        self.originFrameQueue1 = queue.Queue(maxsize=5)
        self.originFrameQueue2 = queue.Queue(maxsize=5)
        self.originFrameQueue3 = queue.Queue(maxsize=5)

        self.faceQueue = queue.Queue(maxsize=5)
        self.poseQueue = queue.Queue(maxsize=5)
        self.fashionQueue = queue.Queue(maxsize=5)
    
    def tcpReceive(self, client_socket, originQ1):
        data = b""
        payload_size = struct.calcsize("L")
        # while True:
        try:
            while not self.exitFlag.is_set():
                # 데이터 수신
                while len(data) < payload_size:
                    packet = client_socket.recv(4 * 1024)
                    if not packet:
                        break
                    data += packet

                # if not data:
                #     break              

                packed_msg_size = data[: payload_size]
                data = data[payload_size :]
                msg_size = struct.unpack("L", packed_msg_size)[0]

                # 데이터 수신
                while len(data) < msg_size:
                    data += client_socket.recv(4 * 1024)

                frame_data = data[:msg_size]
                data = data[msg_size:]
                # 수신된 데이터 디코딩하여 화면에 표시
                frame = pickle.loads(frame_data)
                frame = cv2.imdecode(frame, cv2.IMREAD_COLOR)
                frame = cv2.resize(frame, (640, 480))  # 프레임 크기 조정

                if self.originFrameQueue1.full():
                    self.originFrameQueue1.get()
                
                if self.originFrameQueue2.full():
                    self.originFrameQueue2.get()

                if self.originFrameQueue3.full():
                    self.originFrameQueue3.get()


                self.originFrameQueue1.put(np.copy(frame))
                self.originFrameQueue2.put(np.copy(frame))
                self.originFrameQueue3.put(np.copy(frame))

                time.sleep(0.001) # face

        except Exception as e:
            print("Error tcp Receive from Raspberry : ", e)
        except KeyboardInterrupt:
            print("Server stop command occurred")
        finally:
            self.stop()
             
    def deeplearn(self, originQ1, originQ2, originQ3, faceQ, poseQ, fashionQ):
        while not self.exitFlag.is_set():
            if not originQ1.empty():
                frame1 = originQ1.get()
                # print("originQ1 size : ", originQ.qsize())
                resultFrame1, self.info = self.faceInst.detect_faces_and_info(frame1)

                if faceQ.full():
                    faceQ.get()

                faceQ.put(resultFrame1)
            else:
                pass

            if not originQ2.empty():
                frame2 = originQ2.get()
                ArUcoResult = self.ArUcoInst.measureZcoordinate(frame2)
                if (self.ArUcoInst.coordinateZ2 != 0):
                    resultFrame2 = self.poseInst.measureHeight(frame2)
                    if (self.poseInst.pixelSum != 0):
                        self.height = (self.poseInst.pixelSum * self.ArUcoInst.coordinateZ2 * self.ratio) + 15
                        cv2.putText(resultFrame2, f'height: {self.height:.2f}cm', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 150, 0), 5)
                else:
                    self.height = 0
                    resultFrame2 = frame2

                if poseQ.full():
                    poseQ.get()

                poseQ.put(resultFrame2)

            if not originQ3.empty():
                frame3 = originQ3.get()
                resultFrame3, self.color = self.extract_upper_body(frame3, self.model)

                if fashionQ.full():
                    fashionQ.get()
                
                fashionQ.put(resultFrame3)
            else:
                pass

            time.sleep(0.001)

    def extract_average_color(self, image):
        # Calculate average color
        average_color = np.mean(image, axis=(0, 1))
        return average_color

    def describe_rgb(self, rgb):
        red = rgb[2]
        green = rgb[1]
        blue = rgb[0]
        # print(int(red),'',int(green),'',int(blue))
        # 색상(RGB) 값을 색상 이름으로 변환
        if red < 100 and green < 100 and blue < 100:
            color_name = 'Black'
        elif red > 150 and green > 150 and blue > 150:
            color_name = 'White'
        elif red > green and red > blue:
            if red - green < 15 :
                color_name = 'yellow'
            else:
                color_name = 'Red'
        elif green > red and green > blue:
            color_name = 'Green'
        elif blue > red and blue > green:
            if blue - red < 15:
                color_name = 'purple'
            else:
                color_name = 'Blue'
        else:
            color_name = 'Other'
        # 설명 출력
        # print(f"이 RGB 값은 \"{color_name}\"입니다.")
        return color_name

    def extract_upper_body(self, frame, model):
        results = model(frame, stream=True,verbose=False)
        result_color = 'other'
        for detection in results:
            for i, box in enumerate(detection.boxes.xyxy):
                x1, y1, x2, y2 = map(int, box)
                class_id = int(detection.boxes.cls[i].item())
                class_label = model.names[class_id]
                confidence = float(detection.boxes.conf[i].item())  # 객체의 신뢰도(확률)

                # Display only if the detected class is "person" and confidence is >= 0.9
                if class_label == "person" and confidence >= 0.85:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, f'{class_label} {confidence:.2f}', (x1, y1 + 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    roi = frame[y1:y2, x1:x2]
                    upper_body_region = (10, 65, 140, 190)  # (x1, y1, x2, y2) 형식의 좌표영역

                    # Extract upper body region
                    upper_body_roi = roi[upper_body_region[1]:upper_body_region[3], upper_body_region[0]:upper_body_region[2]]
                    average_color = self.extract_average_color(upper_body_roi)
                    color = self.describe_rgb(average_color)
                    cv2.putText(frame, color, (x1, y1 + 25), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)  # 색상 이름 출력
                    ##upper_body_roi 영역으로 opencv 색 검출 로직 추가 하면됨
                    result_color = color

        return frame,result_color

    def tcpSend(self, faceQ, poseQ, fashionQ):
        try:
            while not self.exitFlag.is_set():
                faceFrame = faceQ.get()
                poseFrame = poseQ.get()
                fashionFrame = fashionQ.get()

                self.combined_frame = np.hstack((faceFrame, poseFrame, fashionFrame))

                if self.client_socket_2:
                    self.send_frame(self.client_socket_2, self.combined_frame)
                else:
                    print("fail send frame")

                if self.client_socket_3:
                    self.send_result(self.client_socket_3, self.color, self.height, self.info)
                else:
                    print("fail send result")

                time.sleep(0.001)
        except Exception as e:
            print("Error tcp send to GUI : ", e)
        finally:
            self.stop()
            
    def send_frame(self, conn, frame):
        # JPEG로 인코딩
        _, buffer = cv2.imencode(".jpg", frame)
        data = pickle.dumps(buffer)

        # 데이터 크기 전송
        size = struct.pack("L", len(data))
        conn.sendall(size)

        # 데이터 전송
        conn.sendall(data)
    
    def send_result(self, conn, color, height, info):
        # 결과를 인코딩하여 전송
        conn.sendall((color + "," + str(height) + "," + info).encode())  # 색상, 높이, 정보 전송
    
    def run(self):
        print("run 메서드 실행")

    def stop(self):
        self.server_socket_1.close()
        self.server_socket_2.close()
        self.server_socket_3.close()
        
        self.exitFlag.set()
        self.tcpReceiveThread.join()
        self.deeplearnThread.join()
        self.tcpSendThread.join()

        print("Terminate server!")
        sys.exit(0)


if __name__ == "__main__":
    main_instance = MainServer()
    main_instance.run()
    sys.exit(0)
