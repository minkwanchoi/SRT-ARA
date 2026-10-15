package logger;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/** 운용 기록 저장 (예외사유 표기법 예제) */
public class DataLogger {

    private final ByteArrayOutputStream buffer = new ByteArrayOutputStream();

    public boolean append(String record) {
        if (record == null) { // SRT-D-ID1-1{@비고{기록 문자열 NULL 방어 코드}}
            return false;
        }
        try {
            buffer.write(record.getBytes(StandardCharsets.UTF_8));
            return true;
        // SRT-D-ID2-1START
        } catch (IOException e) {
            return false;
        }
        // SRT-D-ID2-1END{
        //   @커버리지{문장}
        //   @미달성사유{메모리 버퍼(ByteArrayOutputStream)에 기록하므로 실제로는 IOException 이
        //               발생하지 않으나, write() 의 선언에 따라 예외 처리 구문을 반드시 작성해야
        //               함. 시험으로 해당 분기를 실행시킬 수 없음.}
        //   @요구사항{X-XXX-SFR-041 운용 기록 저장}
        // }
    }

    public int size() {
        return buffer.size();
    }
}
