import platform
import ctypes
import os


# 4  ALM 立即停止                -> ALM Immediate Stop
# 5  ALM 减速停止                -> ALM Deceleration Stop
# 6  间服使能立即停止            -> Servo Enable Immediate Stop
# 7  间服使能减速停止            -> Servo Enable Deceleration Stop
# 8  指令编码器误差立即停止      -> Command Encoder Error Immediate Stop
# 9  指令编码器误差减速停止      -> Command Encoder Error Deceleration Stop
# 10 Index 立即停止             -> Index Immediate Stop
# 11 Index 减速停止             -> Index Deceleration Stop
# 12 原点立即停止               -> Home Position Immediate Stop
# 13 原点减速停止               -> Home Position Deceleration Stop
# 14 正硬限位立即停止           -> Positive Hard Limit Immediate Stop
# 15 正硬限位减速停止           -> Positive Hard Limit Deceleration Stop
# 16 负硬限位立即停止           -> Negative Hard Limit Immediate Stop
# 17 负硬限位减速停止           -> Negative Hard Limit Deceleration Stop
# 18 正软限位立即停止           -> Positive Soft Limit Immediate Stop
# 19 正软限位减速停止           -> Positive Soft Limit Deceleration Stop
# 20 负软限位立即停止           -> Negative Soft Limit Immediate Stop
# 21 负软限位减速停止           -> Negative Soft Limit Deceleration Stop
# 22 命令立即停止               -> Command Immediate Stop
# 23 命令减速停止               -> Command Deceleration Stop
# 24 其它原因立即停止           -> Other Reason Immediate Stop
# 25 其它原因减速停止           -> Other Reason Deceleration Stop
# 26 未知原因立即停止           -> Unknown Reason Immediate Stop
# 27 未知原因减速停止           -> Unknown Reason Deceleration Stop
# 28 外部 IO 减速停止           -> External IO Deceleration Stop


if platform.system() == 'Windows':
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
else:
    kernel32 = None

class SuppressConsole:
    """Context manager to suppress and restore Windows console output."""
    def __enter__(self):
        if kernel32 is None:
            self._windows_handles_available = False
            return self

        self._windows_handles_available = True
        self._stdout = os.dup(1)  # Save original stdout
        self._stderr = os.dup(2)  # Save original stderr
        self._null = os.open(os.devnull, os.O_WRONLY)  # Open null device

        # Get Windows console output handles
        STD_OUTPUT_HANDLE = -11
        STD_ERROR_HANDLE = -12
        self.stdout_handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        self.stderr_handle = kernel32.GetStdHandle(STD_ERROR_HANDLE)

        # Redirect both stdout and stderr
        os.dup2(self._null, 1)
        os.dup2(self._null, 2)
        kernel32.SetStdHandle(STD_OUTPUT_HANDLE, self._null)
        kernel32.SetStdHandle(STD_ERROR_HANDLE, self._null)

    def __exit__(self, exc_type, exc_value, traceback):
        if not getattr(self, "_windows_handles_available", False):
            return

        # Restore stdout and stderr
        os.dup2(self._stdout, 1)
        os.dup2(self._stderr, 2)
        kernel32.SetStdHandle(-11, self.stdout_handle)
        kernel32.SetStdHandle(-12, self.stderr_handle)
        os.close(self._null)

from droplogic.utils.native_runtime import resolve_dll

# Suppress DLL prints while loading
try:
    with SuppressConsole():
        script_dir = os.path.dirname(os.path.abspath(__file__))  
        local_dll_path = os.path.join(script_dir, "MCDLL_NET.dll").replace('\\', '/')
        Dll_Address = resolve_dll('xy_stage/nmc/MCDLL_NET.dll', local_dll_path)
        MCDLL_dll = ctypes.CDLL(Dll_Address, winmode=0) if platform.system() == 'Windows' else None  # Load DLL silently
except (FileNotFoundError, OSError) as e:
    print(f"Warning: Could not load MCDLL_NET.dll - XY stage hardware will not be available. Error: {e}")
    MCDLL_dll = None  # Set to None so we can check if it's loaded before using it

#/********************************************************************************************************************************************************************
#                                                       1 控制卡打开函数
#********************************************************************************************************************************************************************/
#//1.0 网络并联模式设置函数(打开卡前设置)               宏定义1.0
def MCF_Set_Switch_State_Net                 (Mode = 0):
	return MCDLL_dll.MCF_Set_Switch_State_Net                 (Mode)
#//    网卡设置函数(打开卡前设置)                       0:自动搜索网卡  [1,]:用户指定网卡 
def MCF_Set_Card_Number_Net                  (Card_Number = 0): 
	return MCDLL_dll.MCF_Set_Card_Number_Net                  (Card_Number)
def MCF_Get_Card_Number_Net                  (Card_Number): 
	return MCDLL_dll.MCF_Get_Card_Number_Net                  (Card_Number)  
#//1.1 初始化函数                                       [1,100]                          [0,99]                          宏定义1.1                  
def MCF_Open_Net                             (Connection_Number,Station_Number,Station_Type):  
	return MCDLL_dll. MCF_Open_Net                             (Connection_Number,Station_Number,Station_Type)
def MCF_Get_Open_Net                         (Connection_Number,Station_Number,Station_Type):  
	return MCDLL_dll.MCF_Get_Open_Net                         (Connection_Number,Station_Number,Station_Type)
def MCF_Close_Net                            ():   
	return MCDLL_dll.MCF_Close_Net                            ()
#//1.2 链接超时紧急停止函数                             [0,60000]
def MCF_Set_Link_TimeOut_Net                 (Time_1MS,TimeOut_Output,StationNumber = 0): 
	return MCDLL_dll.MCF_Set_Link_TimeOut_Net                 (Time_1MS,TimeOut_Output,StationNumber)
def MCF_Get_Link_TimeOut_Net                 (TimeOut_Number,StationNumber = 0): 
	return MCDLL_dll.MCF_Get_Link_TimeOut_Net                 (TimeOut_Number,StationNumber)
#//    链接超时紧急停止触发使能函数        
def MCF_Set_Trigger_Output_Bit_Net           (Bit_Output_Number,Bit_Output_Enable,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Trigger_Output_Bit_Net           (Bit_Output_Number,Bit_Output_Enable,StationNumber)
#//1.3 链接监测函数
def MCF_Get_Link_State_Net                   (StationNumber = 0): 
	return MCDLL_dll.MCF_Get_Link_State_Net                   (StationNumber)
#//1.4 Windows实时性提升
#//    高精度定时回调函数
def MCF_Set_CallBack_Net                     (CallBack,Time_1MS):
	return MCDLL_dll.MCF_Set_CallBack_Net                     (CallBack,Time_1MS)
#//    获取CPU核个数
def MCF_Get_CPU_All_Number_Net                   (CPU_Number): 
	return MCDLL_dll.MCF_Get_CPU_All_Number_Net                   (CPU_Number)
#//    指定CPU核运行DLL,回调函数线程,任意位置调用生效  [0,CPU_Number)
def MCF_Set_DLL_Thread_Affinity_Mask_Net                   (CPU_Number): 
	return MCDLL_dll.MCF_Set_DLL_Thread_Affinity_Mask_Net                   (CPU_Number)
#//    指定CPU核运行用户线程,线程中任意位置调用生效    [0,CPU_Number)
def MCF_Set_User_Thread_Affinity_Mask_Net                   (CPU_Number): 
	return MCDLL_dll.MCF_Set_User_Thread_Affinity_Mask_Net                   (CPU_Number)
#//    指定CPU核运行用户进程,进程中任意位置调用生效    [0,CPU_Number)
def MCF_Set_User_ProcessAffinity_Mask_Net                   (CPU_Number0): 
	return MCDLL_dll.MCF_Set_User_ProcessAffinity_Mask_Net                   (CPU_Number)
	
#/**************************************************************************************************************************************
#                                                      2 通用输入输出函数
#********************************************************************************************************************************************************************/
#//2.1 通用IO全部输出函数                               [OUT31,OUT0]                     [0,99]        
def MCF_Set_Output_Net                       ( All_Output_Logic, StationNumber = 0):                                                    
	return MCDLL_dll.MCF_Set_Output_Net                       ( All_Output_Logic, StationNumber)
def MCF_Get_Output_Net                       (All_Output_Logic, StationNumber = 0):       
	return MCDLL_dll.MCF_Get_Output_Net                       (All_Output_Logic, StationNumber)
#//2.2 通用IO按位输出函数                               宏定义2.3.1                      宏定义2.3.2                      [0,99]  
def MCF_Set_Output_Bit_Net                   (Bit_Output_Number,Bit_Output_Logic, StationNumber = 0):    
	return MCDLL_dll.MCF_Set_Output_Bit_Net                   (Bit_Output_Number,Bit_Output_Logic, StationNumber)
def MCF_Get_Output_Bit_Net                   (Bit_Output_Number,Bit_Output_Logic,StationNumber = 0):    
	return MCDLL_dll.MCF_Get_Output_Bit_Net                   (Bit_Output_Number,Bit_Output_Logic,StationNumber)
#//    通用IO按位输出阻塞函数,需要等待上个输出完成才退出函数   
def MCF_Set_Output_Block_Bit_Net             (Bit_Output_Number,Bit_Output_Logic, StationNumber = 0): 
	return MCDLL_dll.MCF_Set_Output_Block_Bit_Net             (Bit_Output_Number,Bit_Output_Logic, StationNumber)
#//2.3 通用IO输出复用1：按位输出保持时间函数            宏定义2.3.1                      宏定义2.3.2                      [0,65535]                       [0,99]  
def MCF_Set_Output_Time_Bit_Net              (Bit_Output_Number,Bit_Output_Logic, Output_Time_1MS, StationNumber = 0):
	return MCDLL_dll.MCF_Set_Output_Time_Bit_Net              (Bit_Output_Number,Bit_Output_Logic, Output_Time_1MS, StationNumber)
def MCF_Set_Output_Time_All_Net              (                                 Bit_Output_Logic, Output_Time_1MS, StationNumber = 0):
	return MCDLL_dll.MCF_Set_Output_Time_All_Net              (                                 Bit_Output_Logic, Output_Time_1MS, StationNumber)
#//    通用IO输出复用2：按XY编码器位置输出保持函数      宏定义2.3.1                           [0,1000]                          [-2^31,(2^31-1)]            [0,99]
def MCF_Set_Compare_Output_Bit_Net           (Compare_Output_Number, Compare_Output_1MS,Compare_dDist,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Compare_Output_Bit_Net           (Compare_Output_Number, Compare_Output_1MS,Compare_dDist,StationNumber)
#//2.4 通用IO全部输入函数                               [Input31,Input0]                 [Input48,Input32]               [0,99]  
def MCF_Get_Input_Net                        (All_Input_Logic1, All_Input_Logic2,StationNumber = 0): 
	return MCDLL_dll.MCF_Get_Input_Net                        (All_Input_Logic1, All_Input_Logic2,StationNumber)
#//2.5 通用IO按位输入函数                               宏定义2.4.1                      宏定义2.4.2                     [0,99]  
def MCF_Get_Input_Bit_Net                    (Bit_Input_Number, Bit_Input_Logic,StationNumber = 0):  
	return MCDLL_dll.MCF_Get_Input_Bit_Net                    (Bit_Input_Number, Bit_Input_Logic,StationNumber)

#//2.6 通用IO按位输入下升沿高速捕获清除函数             [Bit_Input_0,Bit_Input_3]        [0,99] 
def MCF_Clear_Input_Fall_Bit_Net             (Bit_Input_Number, StationNumber = 0): 
	return MCDLL_dll.MCF_Clear_Input_Fall_Bit_Net             (Bit_Input_Number, StationNumber)
#//2.7 通用IO按位输入下升沿高速捕获读取函数             [Bit_Input_0,Bit_Input_3]        宏定义2.7                      [0,99] 
def MCF_Get_Input_Fall_Bit_Net               (Bit_Input_Number, Bit_Input_Fall,StationNumber = 0): 
	return MCDLL_dll.MCF_Get_Input_Fall_Bit_Net               (Bit_Input_Number, Bit_Input_Fall,StationNumber)
#//2.8 通用IO按位输入下升沿高速计数读取函数             [Bit_Input_0,Bit_Input_3]        [0,(2^32-1)]                    10个最新编码器锁存数据 &Array[10]     [0,99] 
def MCF_Get_Input_Fall_Count_Bit_Net         (Bit_Input_Number, Input_Count_Fall,Lock_Data_Buffer,StationNumber = 0): 
	return MCDLL_dll.MCF_Get_Input_Fall_Count_Bit_Net         (Bit_Input_Number, Input_Count_Fall,Lock_Data_Buffer,StationNumber)

#//2.9 通用IO按位输入数据锁存保持(最近10个下升沿数据)打开函数(必须在MCF_Open_Net前面提前调用)                                    
def MCF_Open_Input_Lock_Bit_Net              (Lock_Mode = 0,StationNumber = 0): 
	return MCDLL_dll.MCF_Open_Input_Lock_Bit_Net              (Lock_Mode,StationNumber)
#//2.10 通用IO按位输入滤波函数                          [Bit_Input_0,Bit_Input_3]        [1,100]MS                     [0,99] 
def MCF_Set_Input_Filter_Time_Bit_Net        (Bit_Input_Number, Filter_Time_1MS,StationNumber = 0): 
	return MCDLL_dll.MCF_Set_Input_Filter_Time_Bit_Net        (Bit_Input_Number, Filter_Time_1MS,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      3 轴专用输入输出函数
#********************************************************************************************************************************************************************/
#//3.1 伺服使能设置函数                                 宏定义0.0           宏定义3.1                   [0,99] 
def MCF_Set_Servo_Enable_Net                 (Axis,Servo_Logic,StationNumber = 0): 
	return MCDLL_dll.MCF_Set_Servo_Enable_Net                 (Axis,Servo_Logic,StationNumber)
def MCF_Get_Servo_Enable_Net                 (Axis,Servo_Logic,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Servo_Enable_Net                 (Axis,Servo_Logic,StationNumber)
#//3.2 伺服报警复位设置函数                             宏定义0.0           宏定义3.2                   [0,99] 
def MCF_Set_Servo_Alarm_Reset_Net            (Axis,Alarm_Logic,StationNumber = 0):    
	return MCDLL_dll.MCF_Set_Servo_Alarm_Reset_Net            (Axis,Alarm_Logic,StationNumber)
def MCF_Get_Servo_Alarm_Reset_Net            (Axis,Alarm_Logic,StationNumber = 0): 
	return MCDLL_dll.MCF_Get_Servo_Alarm_Reset_Net            (Axis,Alarm_Logic,StationNumber)
#//3.3 伺服报警输入获取函数                             宏定义0.0           宏定义3.3                            [0,99] 
def MCF_Get_Servo_Alarm_Net                  (Axis,Servo_Alarm_State,   StationNumber = 0):
	return MCDLL_dll.MCF_Get_Servo_Alarm_Net                  (Axis,Servo_Alarm_State,   StationNumber)
#//3.4 伺服定位完成输入获取函数                         宏定义0.0           宏定义3.4                            [0,99]
def MCF_Get_Servo_INP_Net                    (Axis,Servo_INP_State,     StationNumber = 0):
	return MCDLL_dll.MCF_Get_Servo_INP_Net                    (Axis,Servo_INP_State,     StationNumber)
#//3.5 编码器Z相输入获取函数                            宏定义0.0           宏定义3.5                            [0,99]
def MCF_Get_Z_Net                            (Axis,Z_State,   StationNumber = 0):
	return MCDLL_dll.MCF_Get_Z_Net                            (Axis,Z_State,   StationNumber)
#//3.6 原点输入获取函数                                 宏定义0.0           宏定义3.6                            [0,99] 
def MCF_Get_Home_Net                         (Axis,Home_State,          StationNumber = 0):
	return MCDLL_dll.MCF_Get_Home_Net                         (Axis,Home_State,          StationNumber)
#//3.7 正限位输入获取函数                               宏定义0.0           宏定义3.7                            [0,99] 
def MCF_Get_Positive_Limit_Net               (Axis,Positive_Limit_State,StationNumber = 0): 
	return MCDLL_dll.MCF_Get_Positive_Limit_Net               (Axis,Positive_Limit_State,StationNumber)
#//3.8 负限位输入获取函数                               宏定义0.0           宏定义3.8                            [0,99] 
def MCF_Get_Negative_Limit_Net               (Axis,Negative_Limit_State,StationNumber = 0):    
	return MCDLL_dll.MCF_Get_Negative_Limit_Net               (Axis,Negative_Limit_State,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      4 轴设置函数
#********************************************************************************************************************************************************************/
#//4.1 脉冲通道输出设置函数                             宏定义0.0           宏定义4.1                 [0,99] 
def MCF_Set_Pulse_Mode_Net                   (Axis,Pulse_Mode,StationNumber = 0):                                                       
	return MCDLL_dll.MCF_Set_Pulse_Mode_Net                   (Axis,Pulse_Mode,StationNumber)
def MCF_Get_Pulse_Mode_Net                   (Axis,Pulse_Mode,StationNumber = 0):    
	return MCDLL_dll.MCF_Get_Pulse_Mode_Net                   (Axis,Pulse_Mode,StationNumber)
#//4.2 位置设置函数                                     宏定义0.0           [-2^31,(2^31-1)] [0,99] 
def MCF_Set_Position_Net                     (Axis,Position,StationNumber = 0):                                                         
	return MCDLL_dll.MCF_Set_Position_Net                     (Axis,Position,StationNumber)
def MCF_Get_Position_Net                     (Axis,Position,StationNumber = 0):   
	return MCDLL_dll.MCF_Get_Position_Net                     (Axis,Position,StationNumber)
#//4.3 编码器设置函数                                  宏定义0.0           [-2^31,(2^31-1)] [0,99]  
def MCF_Set_Encoder_Net                      (Axis,Encoder,StationNumber = 0):                                                            
	return MCDLL_dll.MCF_Set_Encoder_Net                      (Axis,Encoder,StationNumber)
def MCF_Get_Encoder_Net                      (Axis,Encoder,StationNumber = 0):  
	return MCDLL_dll.MCF_Get_Encoder_Net                      (Axis,Encoder,StationNumber)
#//    通过Z相清除AB编码器值
def MCF_Z_Clear_Encoder_Net                  (Axis,Enable,StationNumber = 0):
	return MCDLL_dll.MCF_Z_Clear_Encoder_Net                  (Axis,Enable,StationNumber)
#//    通过Z相后固定距离输出IO                         宏定义0.0            [0,255]              [0,65535]            [0,255]
def MCF_Z_Output_Bit_Net                     (Axis,Number,dDist,Time_1MS,StationNumber = 0):
	return MCDLL_dll.MCF_Z_Output_Bit_Net                     (Axis,Number,dDist,Time_1MS,StationNumber)
#//4.4 速度获取                                        宏定义0.0           [-2^15,(2^15-1)]    [-2^15,(2^15-1)]   [0,99] 
def MCF_Get_Vel_Net                          (Axis,Command_Vel,Encode_Vel,StationNumber = 0):        
	return MCDLL_dll.MCF_Get_Vel_Net                          (Axis,Command_Vel,Encode_Vel,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      5 轴硬件触发停止运动函数
#********************************************************************************************************************************************************************/
#//5.1 通用IO输入复用：做为紧急停止函数                 宏定义2.4.1                      宏定义5.1                [0,99] 
def MCF_Set_EMG_Bit_Net                      (EMG_Input_Number,EMG_Mode,StationNumber = 0): 
	return MCDLL_dll.MCF_Set_EMG_Bit_Net                      (EMG_Input_Number,EMG_Mode,StationNumber)
def MCF_Set_EMG_Output_Net                   (EMG_Input_Number,EMG_Mode,EMG_Output,StationNumber = 0):     
	return MCDLL_dll.MCF_Set_EMG_Output_Net                   (EMG_Input_Number,EMG_Mode,EMG_Output,StationNumber)
def MCF_Set_EMG_Output_Enable_Net            (Bit_Output_Number,Bit_Output_Enable,StationNumber = 0):
	return MCDLL_dll.MCF_Set_EMG_Output_Enable_Net            (Bit_Output_Number,Bit_Output_Enable,StationNumber)
#//    通用IO输入复用：做为触发停止                    [0,3]                   宏定义0.0            [Bit_Input_0,Bit_Input_15]       宏定义5.4                   [0,99] 
def MCF_Set_Input_Trigger_Net                (Channel,Axis,Bit_Input_Number,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Input_Trigger_Net                (Channel,Axis,Bit_Input_Number,Trigger_Mode,StationNumber)
def MCF_Get_Input_Trigger_Net                (Channel,Axis,Bit_Input_Number,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Input_Trigger_Net                (Channel,Axis,Bit_Input_Number,Trigger_Mode,StationNumber)
#//5.2 软件限位触发运动停止函数                         宏定义0.0           [-2^31,2^31]P     >     [-2^31,2^31]P          [0,99] 
def MCF_Set_Soft_Limit_Net                   (Axis,Positive_Position, Negative_Position,StationNumber = 0):                           
	return MCDLL_dll.MCF_Set_Soft_Limit_Net                   (Axis,Positive_Position, Negative_Position,StationNumber)
def MCF_Get_Soft_Limit_Net                   (Axis,Positive_Position,*Negative_Position,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Soft_Limit_Net                   (Axis,Positive_Position,*Negative_Position,StationNumber)
#//5.3 软件限位触发运动停止开关函数                     宏定义0.0           宏定义5.3                        [0,99] 
def MCF_Set_Soft_Limit_Enable_Net            (Axis,Soft_Limit_Enable,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Soft_Limit_Enable_Net            (Axis,Soft_Limit_Enable,StationNumber)
def MCF_Get_Soft_Limit_Enable_Net            (Axis,Soft_Limit_Enable,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Soft_Limit_Enable_Net            (Axis,Soft_Limit_Enable,StationNumber)
#//5.4 伺服报警触发运动停止函数                         宏定义0.0           宏定义5.4                   [0,99] 
def MCF_Set_Alarm_Trigger_Net                (Axis,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Alarm_Trigger_Net                (Axis,Trigger_Mode,StationNumber)
def MCF_Get_Alarm_Trigger_Net                (Axis,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Alarm_Trigger_Net                (Axis,Trigger_Mode,StationNumber)
#//5.5 Index触发运动停止函数                            宏定义0.0           宏定义5.4                   [0,99] 
def MCF_Set_Index_Trigger_Net                (Axis,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Index_Trigger_Net                (Axis,Trigger_Mode,StationNumber)
def MCF_Get_Index_Trigger_Net                (Axis,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Index_Trigger_Net                (Axis,Trigger_Mode,StationNumber)
#//5.6 原点触发运动停止函数                             宏定义0.0           宏定义5.4                   [0,99] 
def MCF_Set_Home_Trigger_Net                 (Axis,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Home_Trigger_Net                 (Axis,Trigger_Mode,StationNumber)
def MCF_Get_Home_Trigger_Net                 (Axis,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Home_Trigger_Net                 (Axis,Trigger_Mode,StationNumber)
#//5.7 正限位触发运动停止函数                           宏定义0.0           宏定义5.4                   [0,99] 
def MCF_Set_ELP_Trigger_Net                  (Axis,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Set_ELP_Trigger_Net                  (Axis,Trigger_Mode,StationNumber)
def MCF_Get_ELP_Trigger_Net                  (Axis,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Get_ELP_Trigger_Net                  (Axis,Trigger_Mode,StationNumber)
#//5.8 负限位触发运动停止函数                           宏定义0.0           宏定义5.4                   [0,99] 
def MCF_Set_ELN_Trigger_Net                  (Axis,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Set_ELN_Trigger_Net                  (Axis,Trigger_Mode,StationNumber)
def MCF_Get_ELN_Trigger_Net                  (Axis,Trigger_Mode,StationNumber = 0):                               
	return MCDLL_dll.MCF_Get_ELN_Trigger_Net                  (Axis,Trigger_Mode,StationNumber)
#//5.9 原点触发位置记录函数 	                           宏定义0.0           [-2^31,(2^31-1)]  [0,99] 		  [0,99]
def MCF_Get_Home_Rise_Position_Net           (Axis,Position,StationNumber = 0):  
	return MCDLL_dll.MCF_Get_Home_Rise_Position_Net           (Axis,Position,StationNumber)
def MCF_Get_Home_Fall_Position_Net           (Axis,Position,StationNumber = 0):   
	return MCDLL_dll.MCF_Get_Home_Fall_Position_Net           (Axis,Position,StationNumber)
def MCF_Get_Home_Rise_Encoder_Net            (Axis,Encoder,StationNumber = 0):  
	return MCDLL_dll.MCF_Get_Home_Rise_Encoder_Net            (Axis,Encoder,StationNumber)
def MCF_Get_Home_Fall_Encoder_Net            (Axis,Encoder,StationNumber = 0):  
	return MCDLL_dll.MCF_Get_Home_Fall_Encoder_Net            (Axis,Encoder,StationNumber)
#//5.10 轴状态清除函数                                  宏定义0.0           [0,99] 
def MCF_Clear_Axis_State_Net                 (Axis,StationNumber = 0):  
	return MCDLL_dll.MCF_Clear_Axis_State_Net                 (Axis,StationNumber)
#//5.11 轴状态触发停止运动查询函数                      宏定义0.0           MC_Retrun.h[0,28]      [0,99] 
def MCF_Get_Axis_State_Net                   (Axis,Reason,StationNumber = 0): 
	return MCDLL_dll.MCF_Get_Axis_State_Net                   (Axis,Reason,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      6 轴回原点函数
#********************************************************************************************************************************************************************/
#//6.1 设置回零参数                                     宏定义0.0           [1,65535]                       [1,65535]
def MCF_Search_Home_dMaxA_Time_Net			 (Axis,H_dMaxA_Time = 10,L_dMaxA_Time = 10,StationNumber = 0):
	return MCDLL_dll.MCF_Search_Home_dMaxA_Time_Net			 (Axis,H_dMaxA_Time,L_dMaxA_Time,StationNumber)
#//                                                     宏定义0.0           [1,35]                          宏定义6.1.1                宏定义6.1.2               宏定义6.1.3                (0,10M]P/S     (0,10M]P/S     [-2^31,(2^31-1)]
def MCF_Search_Home_Set_Net                  (Axis,Search_Home_Mode,Limit_Logic,Home_Logic,Index_Logic,H_dMaxV,L_dMaxV,Offset_Positio = 1000,Trigger_Source = 0,StationNumber = 0):
	return MCDLL_dll.MCF_Search_Home_Set_Net                  (Axis,Search_Home_Mode,Limit_Logic,Home_Logic,Index_Logic,H_dMaxV,L_dMaxV,Offset_Positio,Trigger_Source,StationNumber)
#//6.2 设置回零启动                                     宏定义0.0           [0,99] 
def MCF_Search_Home_Start_Net                (Axis,StationNumber = 0):
	return MCDLL_dll.MCF_Search_Home_Start_Net                (Axis,StationNumber)
#//6.3 设置回零停止                                     宏定义0.0           [0,99] 
def MCF_Search_Home_Stop_Net                 (Axis,StationNumber = 0):
	return MCDLL_dll.MCF_Search_Home_Stop_Net                 (Axis,StationNumber)
#//6.4 获取回零状态                                     宏定义0.0           MC_Retrun.h{0,31,32}       [0,99]    
def MCF_Search_Home_Get_State_Net            (Axis,Home_State,StationNumber = 0):
	return MCDLL_dll.MCF_Search_Home_Get_State_Net            (Axis,Home_State,StationNumber)
#//6.5 设置回零缓停时间                				   宏定义0.0           [0,1000] 单位：ms         [0,99]
def MCF_Search_Home_Stop_Time_Net			 (Axis,Stop_Time,StationNumber = 0):
	return MCDLL_dll.MCF_Search_Home_Stop_Time_Net			 (Axis,Stop_Time,StationNumber)
#//6.6 设置回零完成后保持位置值                         宏定义0.0            [0,99]
def MCF_Search_Home_Keep_Position_Net        (Axis,StationNumber = 0):
	return MCDLL_dll.MCF_Search_Home_Keep_Position_Net        (Axis,StationNumber)
#//6.7 设置回零完成后保持编码器值                       宏定义0.0            [0,99]
def MCF_Search_Home_Keep_Encoder_Net         (Axis,StationNumber = 0):
	return MCDLL_dll.MCF_Search_Home_Keep_Encoder_Net         (Axis,StationNumber)
#//6.8 设置回零在零点位置离开速度                       宏定义0.0            [0,99]
def MCF_Search_Home_Leave_Vel_Net            (Axis,M_dMaxV,StationNumber = 0):
	return MCDLL_dll.MCF_Search_Home_Leave_Vel_Net            (Axis,M_dMaxV,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      7 点位运动控制函数
#********************************************************************************************************************************************************************/
#//7.1 速度控制函数                                     宏定义0.0           (0,10M]P/S    (0,1T]P^2/S  [0,99] 
def MCF_JOG_Net                              (Axis,dMaxV,dMaxA,StationNumber = 0):                                                  
	return MCDLL_dll.MCF_JOG_Net                              (Axis,dMaxV,dMaxA,StationNumber)
#//7.2 单轴运动位置改变函数                             宏定义0.0           [-2^31,(2^31-1)]  宏定义0.3                    [0,99] 
def MCF_Uniaxial_dDist_Change_Net            (Axis,dDist,Position_Mode,StationNumber = 0):   
	return MCDLL_dll.MCF_Uniaxial_dDist_Change_Net            (Axis,dDist,Position_Mode,StationNumber)
#//7.3 单轴运动速度改变函数                             宏定义0.0           (0,10M]P/S   [0,99] 
def MCF_Uniaxial_dMaxV_Change_Net            (Axis,dMaxV,StationNumber = 0):      
	return MCDLL_dll.MCF_Uniaxial_dMaxV_Change_Net            (Axis,dMaxV,StationNumber)
def MCF_Uniaxial_dMaxA_Change_Net            (Axis,dMaxA,StationNumber = 0): 
	return MCDLL_dll.MCF_Uniaxial_dMaxA_Change_Net            (Axis,dMaxA,StationNumber)
#//7.4 单轴曲线函数                                     宏定义0.0           [0,dMaxV]      (0,10M]P/S    (0,1T]P^2/S   (0,100T]P^3/S [0,dMaxV]      宏定义0.4               [0,99] 
def MCF_Set_Axis_Profile_Net                 (Axis,dV_ini,dMaxV,dMaxA,dJerk,dV_end,Profile,StationNumber = 0):     
	return MCDLL_dll.MCF_Set_Axis_Profile_Net                 (Axis,dV_ini,dMaxV,dMaxA,dJerk,dV_end,Profile,StationNumber)
def MCF_Get_Axis_Profile_Net                 (Axis,dV_ini,dMaxV,dMaxA,dJerk,dV_end,Profile,StationNumber = 0):  
	return MCDLL_dll.MCF_Get_Axis_Profile_Net                 (Axis,dV_ini,dMaxV,dMaxA,dJerk,dV_end,Profile,StationNumber)
#//7.5 单轴运动函数                                     宏定义0.0           [-2^31,(2^31-1)]  宏定义0.3                    [0,99] 
def MCF_Uniaxial_Net                         (Axis,dDist,Position_Mode,StationNumber = 0):   
	return MCDLL_dll.MCF_Uniaxial_Net                         (Axis,dDist,Position_Mode,StationNumber)
def MCF_Uniaxial_Time_Net                    (Axis,dDist,StationNumber = 0):
	return MCDLL_dll.MCF_Uniaxial_Time_Net                    (Axis,dDist,StationNumber)
#//7.6 单轴停止曲线函数                                 宏定义0.0           (0,1T]P^2/S   (0,100T]P^3/S 宏定义0.4               [0,99] 
def MCF_Set_Axis_Stop_Profile_Net            (Axis,dMaxA,dJerk,Profile,StationNumber = 0):                    
	return MCDLL_dll.MCF_Set_Axis_Stop_Profile_Net            (Axis,dMaxA,dJerk,Profile,StationNumber)
def MCF_Get_Axis_Stop_Profile_Net            (Axis,dMaxA,dJerk,Profile,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Axis_Stop_Profile_Net            (Axis,dMaxA,dJerk,Profile,StationNumber)
#//7.7 轴停止函数                                       宏定义0.0           宏定义7.7                     [0,99] 
def MCF_Axis_Stop_Net                        (Axis,Axis_Stop_Mode,StationNumber = 0): 
	return MCDLL_dll.MCF_Axis_Stop_Net                        (Axis,Axis_Stop_Mode,StationNumber)
#//7.8 单轴运动改变周期函数                             宏定义0.0           [1,1000]MS           [0,99] 
def MCF_Uniaxial_Cycle_Change_Net            (Axis,Cycle,StationNumber = 0):   
	return MCDLL_dll.MCF_Uniaxial_Cycle_Change_Net            (Axis,Cycle,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      8 插补运动控制函数
#********************************************************************************************************************************************************************/
#//8.1 坐标系曲线函数                                   宏定义0.1                 [0,dMaxV]      (0,10M]P/S    (0,1T]P^2/S   (0,100T]P^3/S [0,dMaxV]      宏定义0.4               [0,99]     
def MCF_Set_Coordinate_Profile_Net           (Coordinate,dV_ini,dMaxV,dMaxA,dJerk,dV_end,Profile,StationNumber = 0): 
	return MCDLL_dll.MCF_Set_Coordinate_Profile_Net           (Coordinate,dV_ini,dMaxV,dMaxA,dJerk,dV_end,Profile,StationNumber)
def MCF_Get_Coordinate_Profile_Net           (Coordinate,dV_ini,dMaxV,dMaxA,dJerk,dV_end,Profile,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Coordinate_Profile_Net           (Coordinate,dV_ini,dMaxV,dMaxA,dJerk,dV_end,Profile,StationNumber)
#//8.2 圆半径插补运动函数                               宏定义0.1                 宏定义0.0                 [-2^31,(2^31-1)] [-2^31,(2^31-1)]  宏定义0.5                 宏定义0.3                    [0,99] 
def MCF_Arc2_Radius_Net                      (Coordinate,Axis_List,dDist_List,Arc_Radius,  Direction, Position_Mode,StationNumber = 0): 
	return MCDLL_dll.MCF_Arc2_Radius_Net                      (Coordinate,Axis_List,dDist_List,Arc_Radius,  Direction, Position_Mode,StationNumber)
#//8.3 圆圆心插补运动函数                               宏定义0.1                 宏定义0.0                 [-2^31,(2^31-1)] [-2^31,(2^31-1)]  宏定义0.5                 宏定义0.3                    [0,99] 
def MCF_Arc2_Centre_Net                      (Coordinate,Axis_List,dDist_List,Center_List,Direction,Position_Mode,StationNumber = 0): 
	return MCDLL_dll.MCF_Arc2_Centre_Net                      (Coordinate,Axis_List,dDist_List,Center_List,Direction,Position_Mode,StationNumber)
#//8.4 直线插补运动函数                                 宏定义0.1                 宏定义0.0                 [-2^31,(2^31-1)] 宏定义0.3                   [0,99] 
def MCF_Line2_Net                            (Coordinate,Axis_List,dDist_List,Position_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Line2_Net                            (Coordinate,Axis_List,dDist_List,Position_Mode,StationNumber)
def MCF_Line3_Net                            (Coordinate,Axis_List,dDist_List,Position_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Line3_Net                            (Coordinate,Axis_List,dDist_List,Position_Mode,StationNumber)
def MCF_Line4_Net                            (Coordinate,Axis_List,dDist_List,Position_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Line4_Net                            (Coordinate,Axis_List,dDist_List,Position_Mode,StationNumber)
#//8.5 坐标系停止曲线函数                               宏定义0.1                 (0,1T]P^2/S   (0,100T]P^3/S  宏定义0.4               [0,99] 
def MCF_Set_Coordinate_Stop_Profile_Net      (Coordinate,dMaxA,dJerk,Profile,StationNumber = 0):                  
	return MCDLL_dll.MCF_Set_Coordinate_Stop_Profile_Net      (Coordinate,dMaxA,dJerk,Profile,StationNumber)
def MCF_Get_Coordinate_Stop_Profile_Net      (Coordinate,dMaxA,dJerk,Profile,StationNumber = 0): 
	return MCDLL_dll.MCF_Get_Coordinate_Stop_Profile_Net      (Coordinate,dMaxA,dJerk,Profile,StationNumber)
#//8.6 螺旋线圆半径插补运动函数                         宏定义0.1                 宏定义0.0                 [-2^31,(2^31-1)] [-2^31,(2^31-1)]  宏定义0.5                 宏定义0.3                    [0,99] 
def MCF_Screw3_Radius_Net                    (Coordinate,Axis_List,dDist_List,Arc_Radius,Direction,Position_Mode,StationNumber = 0): 
	return MCDLL_dll.MCF_Screw3_Radius_Net                    (Coordinate,Axis_List,dDist_List,Arc_Radius,Direction,Position_Mode,StationNumber)
#//8.7 螺旋线圆圆心插补运动函数                         宏定义0.1                 宏定义0.0                 [-2^31,(2^31-1)] [-2^31,(2^31-1)]  宏定义0.5                 宏定义0.3                    [0,99] 
def MCF_Screw3_Centre_Net                    (Coordinate,Axis_List,dDist_List,Center_List,Direction,Position_Mode,StationNumber = 0): 
	return MCDLL_dll.MCF_Screw3_Centre_Net                    (Coordinate,Axis_List,dDist_List,Center_List,Direction,Position_Mode,StationNumber)
#//8.8 坐标系停止函数                                   宏定义0.1                 宏定义5.6                           [0,99] 
def MCF_Coordinate_Stop_Net                  (Coordinate,Coordinate_Stop_Mode,StationNumber = 0):                                                
	return MCDLL_dll.MCF_Coordinate_Stop_Net                  (Coordinate,Coordinate_Stop_Mode,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      9 缓冲区函数
#********************************************************************************************************************************************************************/
#//9.1 缓冲区停止曲线函数                               宏定义0.2                    (0,1T]P^2/S    (0,100T]P^3/S  宏定义0.4              [0,99]
def MCF_Buffer_Set_Stop_Profile_Net          (Buffer_Number,dMaxA,dJerk,Profile,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Set_Stop_Profile_Net          (Buffer_Number,dMaxA,dJerk,Profile,StationNumber)
#//9.2 缓冲区停止函数                                   宏定义0.2                    宏定义9.2                       [0,99] 
def MCF_Buffer_Stop_Net                      (Buffer_Number,Buffer_Stop_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Stop_Net                      (Buffer_Number,Buffer_Stop_Mode,StationNumber)
#//9.3 缓冲区在线改变速度倍率                           宏定义0.2                    (0,10]                [0,99] 
def MCF_Buffer_Change_Velocity_Ratio_Net     (Buffer_Number,Velocity_Ratio,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Change_Velocity_Ratio_Net     (Buffer_Number,Velocity_Ratio,StationNumber)
#//9.4 缓冲区建立开始函数                               宏定义0.2                    [0,99] 
def MCF_Buffer_Start_Net                     (Buffer_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Start_Net                     (Buffer_Number,StationNumber)
#//9.5 缓冲区速度倍率                                   宏定义0.2                    宏定义9.5                                [0,99] 
def MCF_Buffer_Set_Velocity_Ratio_Enable_Net (Buffer_Number,Velocity_Ratio_Enable = 0,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Set_Velocity_Ratio_Enable_Net (Buffer_Number,Velocity_Ratio_Enable,StationNumber)
#//9.6 缓冲区前瞻处理降速比                             宏定义0.2                    (0,1]                   [0,99]
def MCF_Buffer_Set_Reduce_Ratio_Net          (Buffer_Number,Reduce_Ratio = 1,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Set_Reduce_Ratio_Net          (Buffer_Number,Reduce_Ratio,StationNumber)
#//9.7 缓冲区曲线函数                                   宏定义0.2                    [0,dMaxV]     (0,10M]P/S    (0,1T]P^2/S  (0,100T]P^3/S [0,dMaxV]     宏定义0.4               [0,99]  
def MCF_Buffer_Set_Profile_Net               (Buffer_Number,dV_ini,dMaxV,dMaxA,dJerk,dV_end,Profile,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Set_Profile_Net               (Buffer_Number,dV_ini,dMaxV,dMaxA,dJerk,dV_end,Profile,StationNumber)
#//9.8 缓冲区单轴运动                                   宏定义0.2                    宏定义0.0           [-2^31,(2^31-1)]  宏定义0.3                    [0,99] 
def MCF_Buffer_Uniaxial_Net                  (Buffer_Number,Axis,dDist,Position_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Uniaxial_Net                  (Buffer_Number,Axis,dDist,Position_Mode,StationNumber)
#//    缓冲区单轴运动距离同步跟随函数  
def MCF_Buffer_Sync_Follow_Net               (Buffer_Number,Axis,dDist,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Sync_Follow_Net               (Buffer_Number,Axis,dDist,StationNumber)
#//9.9 缓冲区直线插补运动                               宏定义0.2                    宏定义0.0                 [-2^31,(2^31-1)] 宏定义0.3                    [0,99] 
def MCF_Buffer_Line2_Net                     (Buffer_Number,Axis_List,dDist_List,Position_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Line2_Net                     (Buffer_Number,Axis_List,dDist_List,Position_Mode,StationNumber)
def MCF_Buffer_Line3_Net                     (Buffer_Number,Axis_List,dDist_List,Position_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Line3_Net                     (Buffer_Number,Axis_List,dDist_List,Position_Mode,StationNumber)
def MCF_Buffer_Line4_Net                     (Buffer_Number,Axis_List,dDist_List,Position_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Line4_Net                     (Buffer_Number,Axis_List,dDist_List,Position_Mode,StationNumber)
#//9.10 缓冲区平面圆半径插补运动函数                    宏定义0.2                    宏定义0.0                 [-2^31,(2^31-1)] [-2^31,(2^31-1)]  宏定义0.5                宏定义0.3                    [0,99] 
def MCF_Buffer_Arc_Radius_Net                (Buffer_Number,Axis_List,dDist_List,Arc_Radius,  Direction,Position_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Arc_Radius_Net                (Buffer_Number,Axis_List,dDist_List,Arc_Radius,  Direction,Position_Mode,StationNumber)
#//9.11 缓冲区平面圆圆心插补运动函数                    宏定义0.2                    宏定义0.0                 [-2^31,(2^31-1)] [-2^31,(2^31-1)]  宏定义0.5                宏定义0.3                    [0,99] 
def MCF_Buffer_Arc_Centre_Net                (Buffer_Number,Axis_List,dDist_List,Center_List,Direction,Position_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Arc_Centre_Net                (Buffer_Number,Axis_List,dDist_List,Center_List,Direction,Position_Mode,StationNumber)
#//9.12 缓冲区延时函数                                  宏定义0.2                    [0,2^31-1]           [0,99]
def MCF_Buffer_Delay_Net                     (Buffer_Number,number,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Delay_Net                     (Buffer_Number,number,StationNumber)
#//9.13 缓冲区IO输出函数                                宏定义0.2                    宏定义2.3.1               宏定义2.3.2          [0,99]     
def MCF_Buffer_Set_Output_Bit_Net            (Buffer_Number,Bit_Number,output,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Set_Output_Bit_Net            (Buffer_Number,Bit_Number,output,StationNumber)
#//9.14 缓冲区IO等待函数                                宏定义0.2                    宏定义2.4.1               宏定义2.4.2          (0,2^15-1]              [0,99] 
def MCF_Buffer_Wait_Input_Bit_Net            (Buffer_Number,Bit_Number,Logic,Time_Out,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Wait_Input_Bit_Net            (Buffer_Number,Bit_Number,Logic,Time_Out,StationNumber)
#//9.15 缓冲区建立结束                                  宏定义0.2                    [0,99] 
def MCF_Buffer_End_Net                       (Buffer_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_End_Net                       (Buffer_Number,StationNumber)
#//9.16 缓冲区执行函数                                  宏定义0.2                    宏定义9.16                  [0,99]
def MCF_Buffer_Execute_Net                   (Buffer_Number,Execute_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Execute_Net                   (Buffer_Number,Execute_Mode,StationNumber)
#//9.17 缓冲区断点启动函数                              宏定义0.2                    [0,99]
def MCF_Buffer_Execute_BreakPoint_Net        (Buffer_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Execute_BreakPoint_Net        (Buffer_Number,StationNumber)
#//9.18 缓冲区状态查询函数                              宏定义0.2                    MC_Retrun.h{0,29,30}                   [0,2^15-1]
def MCF_Buffer_Get_State_Net                 (Buffer_Number,Execute_State,Execute_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Get_State_Net                 (Buffer_Number,Execute_State,Execute_Number,StationNumber)
#//9.19 缓冲区剩余可插入指令空间百分比查询              宏定义0.2                    [0,100]
def MCF_Buffer_Get_Remainder_Space_Net        (Buffer_Number,Remainder_Space_Ratio,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Get_Remainder_Space_Net        (Buffer_Number,Remainder_Space_Ratio,StationNumber)
#//9.20 缓冲区开始插入(建议查询到剩余有一半以上空间)    宏定义0.2                    [0,99] 
def MCF_Buffer_Insert_Start_Net               (Buffer_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Insert_Start_Net               (Buffer_Number,StationNumber)
#//9.21 缓冲区结束插入                                  宏定义0.2                    [0,99] 
def MCF_Buffer_Insert_End_Net                 (Buffer_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Insert_End_Net                 (Buffer_Number,StationNumber)
#//9.22 计算加入指令所占用的空间百分比                    宏定义0.2                  [0,100]                            [0,99] 
#//     在MCF_Buffer_Start_Net或者MCF_Buffer_Insert_Start_Net后开始从0计算
def MCF_Buffer_Count_Occupy_Space_Net        (Buffer_Number,Occupy_Space_Ratio,StationNumber = 0):
	return MCDLL_dll.MCF_Buffer_Count_Occupy_Space_Net        (Buffer_Number,Occupy_Space_Ratio,StationNumber)

#/********************************************************************************************************************************************************************
#                                                      10 示波器10K采样频率数据捕捉函数
#********************************************************************************************************************************************************************/
#//10.1 数据捕捉打开/关闭函数(必须在MCF_Open_Net前面提前调用,而且只支持一个运动控制卡)                                    
def MCF_Capture_Open_Net                     (Capture_Mode = 0):
	return MCDLL_dll.MCF_Capture_Open_Net                     (Capture_Mode)
def MCF_Capture_Close_Net                    ():
	return MCDLL_dll.MCF_Capture_Close_Net                    ()
#//10.2 数据捕捉检查数据更新函数                        宏定义10.2            
def MCF_Capture_State_Net                    (Capture_State):
	return MCDLL_dll.MCF_Capture_State_Net                    (Capture_State)
#//10.3 读取采样连续的10000个位置命令数据                宏定义0.0           &Array[Capture_Frequency*Capture_Time_1MS]  
def MCF_Capture_Read_Command_Net             (Axis,Command):
	return MCDLL_dll.MCF_Capture_Read_Command_Net             (Axis,Command)
#//10.4 读取采样连续的10000个编码器数据                  宏定义0.0           &Array[Capture_Frequency*Capture_Time_1MS]
def MCF_Capture_Read_Encoder_Net             (Axis,Encoder):
	return MCDLL_dll.MCF_Capture_Read_Encoder_Net             (Axis,Encoder)
#//10.5 读取采样连续的50000个模拟量数据                  宏定义0.0           &Array[Capture_Frequency*Capture_Time_1MS]
def MCF_Capture_Read_AD_Net                  (Axis,AD):
	return MCDLL_dll.MCF_Capture_Read_AD_Net                  (Axis,AD)
#//10.6 ADC采样滤波                                     宏定义0.0           [0,1]
def MCF_Capture_Filter_AD_Net                (Axis,Filter_Coefficient = 1):
	return MCDLL_dll.MCF_Capture_Filter_AD_Net                (Axis,Filter_Coefficient)
#//10.7 数据捕捉频率设置                                宏定义10.7            
def MCF_Capture_Frequency_Net                (Capture_Frequency = 1,StationNumber = 0):
	return MCDLL_dll.MCF_Capture_Frequency_Net                (Capture_Frequency,StationNumber)
#//10.8 数据捕捉缓存时间设置                            [2,1000] 2的倍数            
def MCF_Capture_Time_Net                     (Capture_Time_1MS = 100,StationNumber = 0):
	return MCDLL_dll.MCF_Capture_Time_Net                     (Capture_Time_1MS,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      11 电子齿轮控制函数
#********************************************************************************************************************************************************************/
#//11.1 电子齿轮设置函数                                宏定义0.0           宏定义0.0                   (0,(2^31-1)]               (0,(2^31-1)]            宏定义11.1.1                  宏定义11.1.2         [0,99]
def MCF_Set_Gear_Net                         (Axis,Follow_Axis,Denominator,Molecule,Follow_Source,Dir,StationNumber = 0): #//关闭使能再使能数据有效
	return MCDLL_dll.MCF_Set_Gear_Net                         (Axis,Follow_Axis,Denominator,Molecule,Follow_Source,Dir,StationNumber)
def MCF_Get_Gear_Net                         (Axis,Follow_Axis,Denominator,Molecule,Follow_Source,Dir,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Gear_Net                         (Axis,Follow_Axis,Denominator,Molecule,Follow_Source,Dir,StationNumber)
#//11.2 电子齿轮开关函数                                宏定义0.0           宏定义11.2                  [0,99] 
def MCF_Set_Gear_Enable_Net                  (Axis, Gear_Enable,StationNumber = 0): 
	return MCDLL_dll.MCF_Set_Gear_Enable_Net                  (Axis, Gear_Enable,StationNumber)
def MCF_Get_Gear_Enable_Net                  (Axis,Gear_Enable,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Gear_Enable_Net                  (Axis,Gear_Enable,StationNumber)
#//11.3 电子齿轮运动距离后自动关闭                      宏定义0.0           [-2^31,(2^31-1)] [0,99] 
def MCF_Set_Gear_Auto_Disable_Net            (Axis,dDist,      StationNumber = 0): 
	return MCDLL_dll.MCF_Set_Gear_Auto_Disable_Net            (Axis,dDist,      StationNumber)
#/********************************************************************************************************************************************************************
#                                                      12 位置比较输出函数
#********************************************************************************************************************************************************************/
#//12.1 设置一维位置比较器                              宏定义0.0                                
def MCF_Set_Compare_Config_Net               (Axis,Enable,Compare_Source,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Compare_Config_Net               (Axis,Enable,Compare_Source,StationNumber)
def MCF_Get_Compare_Config_Net               (Axis,Enable,Compare_Source,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Compare_Config_Net               (Axis,Enable,Compare_Source,StationNumber)
#//12.2 清除一维位置所有/当前比较点/关闭任意点          宏定义0.0
def MCF_Clear_Compare_Points_Net             (Axis,StationNumber = 0):
	return MCDLL_dll.MCF_Clear_Compare_Points_Net             (Axis,StationNumber)
def MCF_Clear_Compare_Current_Points_Net     (Axis,StationNumber = 0):
	return MCDLL_dll.MCF_Clear_Compare_Current_Points_Net     (Axis,StationNumber)
#//    按照 MCF_Add_Compare_Point_Net 数据累加计算      宏定义0.0           [1,(2^31-1)}
def MCF_Disable_Compare_Any_Points_Net       (Axis,Point_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Disable_Compare_Any_Points_Net       (Axis,Point_Number,StationNumber)
#//12.3 添加一维位置比较点                              宏定义0.0
def MCF_Add_Compare_Point_Net                (Axis,Position,Dir, Action,Actpara,StationNumber = 0):
	return MCDLL_dll.MCF_Add_Compare_Point_Net                (Axis,Position,Dir, Action,Actpara,StationNumber)
#//                                                     宏定义0.0                                              宏定义11.2
def MCF_Add_Compare_Gear_Net                 (Axis,Position,Dir, Gear_Enable,Gear_Axis,StationNumber = 0):
	return MCDLL_dll.MCF_Add_Compare_Gear_Net                 (Axis,Position,Dir, Gear_Enable,Gear_Axis,StationNumber)
#//                                                     宏定义0.0                                              宏定义7.7  
def MCF_Add_Compare_Stop_Net                 (Axis,Position,Dir, Stop_Mode,Stop_Axis,StationNumber = 0):
	return MCDLL_dll.MCF_Add_Compare_Stop_Net                 (Axis,Position,Dir, Stop_Mode,Stop_Axis,StationNumber)
#//                                                     宏定义0.0                                              [0,99]
def MCF_Add_Compare_dMaxV_Net                (Axis,Position,Dir, dMaxV_Ratio,dMaxV_Axis,StationNumber = 0):
	return MCDLL_dll.MCF_Add_Compare_dMaxV_Net                (Axis,Position,Dir, dMaxV_Ratio,dMaxV_Axis,StationNumber)
#//12.4 读取当前一维比较点位置                          宏定义0.0
def MCF_Get_Compare_Current_Point_Net        (Axis,Position,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Compare_Current_Point_Net        (Axis,Position,StationNumber)
#//12.5 查询已经比较过的一维比较点个数(注意数据溢出)    宏定义0.0           [0,256]  
def MCF_Get_Compare_Points_Runned_Net        (Axis,Point_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Compare_Points_Runned_Net        (Axis,Point_Number,StationNumber)
#//12.6 查询可以加入的一维比较点个数                    宏定义0.0           [0,256]
def MCF_Get_Compare_Points_Remained_Net      (Axis,Point_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Compare_Points_Remained_Net      (Axis,Point_Number,StationNumber)
#//12.7 查询所有未完成一维比较点个数和位置              宏定义0.0               
def MCF_Get_Compare_Points_Incomplete_Net    (Axis,Incomplete_Number,Incomplete_Position,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Compare_Points_Incomplete_Net    (Axis,Incomplete_Number,Incomplete_Position,StationNumber)
#//12.8 设置一维位置比较器光源频闪功能                  宏定义0.0 
def MCF_Set_Compare_Light_Frequency_Net      (Axis,Light_Number,Frequency_Enable,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Compare_Light_Frequency_Net      (Axis,Light_Number,Frequency_Enable,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      13 PWM输出函数
#********************************************************************************************************************************************************************/
#//13.1 设置PWM输出参数                                 宏定义13.1.1            宏定义13.1.2           宏定义13.1.3                       宏定义13.1.4
def MCF_Set_Pwm_Config_Net                   (Channel, Enable,Output_Port_Config,Output_Start_Logic,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Pwm_Config_Net                   (Channel, Enable,Output_Port_Config,Output_Start_Logic,StationNumber)
def MCF_Get_Pwm_Config_Net                   (Channel,Enable,Output_Port_Config,Output_Start_Logic,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Pwm_Config_Net                   (Channel,Enable,Output_Port_Config,Output_Start_Logic,StationNumber)
#//13.2 输出PWM信号                                     宏定义13.1.1            [0,1000000]            [0,100]                  (0,(2^31-1)] 
def MCF_Set_Pwm_Output_Net                   (Channel,Frequency,DutyCycle,Pwm_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Pwm_Output_Net                   (Channel,Frequency,DutyCycle,Pwm_Number,StationNumber)
#//13.3 PWM完成信号                                     宏定义13.1.1            宏定义13.3.1 
def MCF_Get_Pwm_State_Net                    (Channel,Finish,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Pwm_State_Net                    (Channel,Finish,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      14 手轮函数
#********************************************************************************************************************************************************************/
#//14.1 开启手轮功能                                    宏定义11.1.2 
def MCF_Hand_Wheel_Open_Net                  (Dir,StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Open_Net                  (Dir,StationNumber)
#//14.2 关闭手轮功能
def MCF_Hand_Wheel_Close_Net                 (StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Close_Net                 (StationNumber)
#//14.3 设置硬件手轮编码器通道                          宏定义0.0                        
def MCF_Hand_Wheel_Config_Encoder_Net        (Axis,StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Config_Encoder_Net        (Axis,StationNumber)
#//14.4 设置硬件手轮速率配置输入点                      宏定义2.4.1                     
def MCF_Hand_Wheel_Config_X1_Net             (Bit_Input_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Config_X1_Net             (Bit_Input_Number,StationNumber)
def MCF_Hand_Wheel_Config_X10_Net            (Bit_Input_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Config_X10_Net            (Bit_Input_Number,StationNumber)
def MCF_Hand_Wheel_Config_X100_Net           (Bit_Input_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Config_X100_Net           (Bit_Input_Number,StationNumber)
#//14.5 设置硬件手轮速率大小                                                [1,100]
def MCF_Hand_Wheel_Speed_X1_Net              (Speed_X = 1,  StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Speed_X1_Net              (Speed_X,  StationNumber)
def MCF_Hand_Wheel_Speed_X10_Net             (Speed_X = 10, StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Speed_X10_Net             (Speed_X, StationNumber)
def MCF_Hand_Wheel_Speed_X100_Net            (Speed_X = 100,StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Speed_X100_Net            (Speed_X,StationNumber)
#//14.6 设置硬件手轮轴号配置输入点                      宏定义0.0           宏定义2.4.1
def MCF_Hand_Wheel_Config_Axis_Net           (Axis,Bit_Input_Number,StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Config_Axis_Net           (Axis,Bit_Input_Number,StationNumber)
#//14.7 设置手轮运动平滑滤波时间                        宏定义0.0           [1,1000]MS 
def MCF_Hand_Wheel_Config_Filter_Time_Net    (Axis,Filter_Time_1MS,StationNumber = 0):
	return MCDLL_dll.MCF_Hand_Wheel_Config_Filter_Time_Net    (Axis,Filter_Time_1MS,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      15 模拟量输入输出函数
#********************************************************************************************************************************************************************/
#//15.1 读取单次ADC采样                                 宏定义0.0           [-2^15,(2^15-1)]
def MCF_Single_Read_AD_Net                   (Channel,AD,StationNumber = 0):
	return MCDLL_dll.MCF_Single_Read_AD_Net                   (Channel,AD,StationNumber)
#//15.2 设置单次DAC输出                                 宏定义0.0           [-2^15,(2^15-1)]
def MCF_Single_Write_DA_Net                  (Channel,DA,StationNumber = 0):
	return MCDLL_dll.MCF_Single_Write_DA_Net                  (Channel,DA,StationNumber)
#/********************************************************************************************************************************************************************
#                                                      16 光源控制器函数
#********************************************************************************************************************************************************************/
#//16.1 设置光源模式(1MS阻塞函数)                       宏定义16.1.1           0：关闭 1:24V常亮 2:24V频闪 3:48V爆闪  
def MCF_Set_Light_Mode_Net                   (Channel,Light_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Light_Mode_Net                   (Channel,Light_Mode,StationNumber)
#//16.2 设置电流保护(1MS阻塞函数)                       宏定义16.1.1           0:关闭功能 常亮:[1,2999] 频闪[1,14999] 单位：MA        
def MCF_Set_Light_Current_Net                (Channel,Max_Current,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Light_Current_Net                (Channel,Max_Current,StationNumber)
def MCF_Get_Light_Current_Net            (Number,Current,StationNumber = 0):
	return MCDLL_dll.MCF_Get_Light_Current_Net            (Number,Current,StationNumber)
#//16.3 设置光源输出(1MS阻塞函数)                       宏定义16.1.1           常亮:[0,255] 频闪[0,1000]
def MCF_Set_Light_Output_Net                 (Channel,Light_Size,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Light_Output_Net                 (Channel,Light_Size,StationNumber)
#//16.4 设置输入触发光源输出                            宏定义16.1.1                                            0：关闭外部触发 1:底电平触发 2:高电平触发  
def MCF_Set_Light_Trigger_Net                (Channel,Bit_Input_Number,Trigger_Mode,StationNumber = 0):
	return MCDLL_dll.MCF_Set_Light_Trigger_Net                (Channel,Bit_Input_Number,Trigger_Mode,StationNumber)
#/********************************************************************************************************************************************************************
#                                                       17 系统函数
#********************************************************************************************************************************************************************/
#//17.1 模块版本号(1MS阻塞函数)                        [0x00000000,0xFFFFFFFF] [0,99] 
def MCF_Get_Version_Net                      (Version,StationNumber = 0):      
	return MCDLL_dll.MCF_Get_Version_Net                      (Version,StationNumber)
def MCF_Get_Version_E_Net                    (Version,StationNumber = 0):  
	return MCDLL_dll.MCF_Get_Version_E_Net                    (Version,StationNumber)
#//17.2 序列号(1MS阻塞函数)                            [0x00000000,0xFFFFFFFF] [0,99] 
def MCF_Get_Serial_Number_Net                (Serial_Number,StationNumber = 0):     
	return MCDLL_dll.MCF_Get_Serial_Number_Net                (Serial_Number,StationNumber)
#//17.3 模块运行时间(1MS阻塞函数)                      [0x00000000,0xFFFFFFFF] [0,99]    单位：秒
def MCF_Get_Run_Time_Net                     (Run_Time,StationNumber = 0): 
	return MCDLL_dll.MCF_Get_Run_Time_Net                     (Run_Time,StationNumber)
#//17.4 Flash 读写功能目前暂时大小2Kbytes,也即定义一个 unsigned int Array[256] 存放数据
def MCF_Flash_Write_Net                      (Pass_Word_Setup,Flash_Write_Data,StationNumber = 0):
	return MCDLL_dll.MCF_Flash_Write_Net                      (Pass_Word_Setup,Flash_Write_Data,StationNumber)
def MCF_Flash_Read_Net                       (Pass_Word_Check,Flash_Read_Data,StationNumber = 0):
	return MCDLL_dll.MCF_Flash_Read_Net                       (Pass_Word_Check,Flash_Read_Data,StationNumber)
#//17.5 开启网络回路,一发一收，正常控制使用(默认)   
def MCF_LookBack_Enable_Net                  ():
	return MCDLL_dll.MCF_LookBack_Enable_Net                  ()
#//17.6 关闭网络回路，只发不收，测试老化模式下使用,或者检测各个级联模块是否工作
def MCF_LookBack_Disable_Net                 ():
	return MCDLL_dll.MCF_LookBack_Disable_Net                 ()
#//17.7 通讯时间监测                                    &Array[12]
def MCF_Get_Connect_Time_Count_Net           (Connect_Count): 
	return MCDLL_dll.MCF_Get_Connect_Time_Count_Net           (Connect_Count)
#//17.8 系统日志函数
def MCF_Set_Log_Enable_Net                   (Code,Enable):
	return MCDLL_dll.MCF_Set_Log_Enable_Net                   (Code,Enable)
def MCF_Get_Log_Count_Net                    (Count):
	return MCDLL_dll.MCF_Get_Log_Count_Net                    (Count)
def MCF_Get_Log_Data_Net                     (Count,Return,Code,Length,Data,StationNumber,Log):
	return MCDLL_dll.MCF_Get_Log_Data_Net                     (Count,Return,Code,Length,Data,StationNumber,Log)

# def py_MCF_Open_Net(connection_Number, station_Number, station_Type):
#     Dll_Address.MCF_Open_Net(connection_Number, station_Number, station_Type)
