# 예제: makefile 에서 소스 구성을 읽는 것을 보이기 위한 것 (C/C++ 부분만 빌드 대상).
# 이름이 *.mk 라서 폴더를 열 때 대표 프로젝트 파일로 고르지 않는다. 직접 고르면 그 구성대로 열린다.
CC  ?= gcc
CXX ?= g++

C_SRCS   = motor_ctrl.c
CXX_SRCS = $(wildcard comm/*.cpp)
OBJS     = $(C_SRCS:.c=.o) $(CXX_SRCS:.cpp=.o)

fcs_app: $(OBJS)
	$(CXX) -o $@ $^

%.o: %.c
	$(CC) -c $< -o $@

%.o: %.cpp
	$(CXX) -c $< -o $@

clean:
	rm -f fcs_app $(OBJS)
