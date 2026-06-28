#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>

#define BUFFER_SIZE 1024 * 1024 // 1MB buffer

void print_header() {
    printf("\033[1;36m┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\033[0m\n");
    printf("\033[1;36m┃\033[0m \033[1;35m🚀 DELUX DISK BENCHMARK (C Engine)\033[0m                  \033[1;36m┃\033[0m\n");
    printf("\033[1;36m┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\033[0m\n\n");
}

int main(int argc, char *argv[]) {
    int mb_to_write = 100; // Default 100MB
    if (argc > 1) {
        mb_to_write = atoi(argv[1]);
    }

    if (mb_to_write <= 0) {
        printf("Error: Invalid size. Please specify a positive number of MB.\n");
        return 1;
    }

    print_header();
    printf("\033[1mTarget size:\033[0m %d MB\n", mb_to_write);
    printf("\033[1mBuffer size:\033[0m 1 MB\n\n");

    char *data = malloc(BUFFER_SIZE);
    if (!data) {
        perror("Failed to allocate buffer");
        return 1;
    }
    // Fill buffer with dummy data
    memset(data, 'A', BUFFER_SIZE);

    const char *test_file = ".delux_bench_test";
    
    // --- WRITE TEST ---
    printf("[\033[1;33m...\033[0m] Testing \033[1mSequential Write\033[0m...\r");
    fflush(stdout);

    int fd = open(test_file, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        perror("\nFailed to open test file for writing");
        free(data);
        return 1;
    }

    clock_t start = clock();
    for (int i = 0; i < mb_to_write; i++) {
        if (write(fd, data, BUFFER_SIZE) != BUFFER_SIZE) {
            perror("\nWrite failed");
            close(fd);
            free(data);
            return 1;
        }
    }
    fsync(fd); // Ensure data is on disk
    clock_t end = clock();
    close(fd);

    double write_time = ((double)(end - start)) / CLOCKS_PER_SEC;
    double write_speed = mb_to_write / write_time;

    printf("[\033[1;32mOK\033[0m] \033[1mSequential Write:\033[0m \033[1;32m%.2f MB/s\033[0m (%d MB in %.3fs)\n", 
           write_speed, mb_to_write, write_time);

    // --- READ TEST ---
    printf("[\033[1;33m...\033[0m] Testing \033[1mSequential Read\033[0m...\r");
    fflush(stdout);

    fd = open(test_file, O_RDONLY);
    if (fd < 0) {
        perror("\nFailed to open test file for reading");
        free(data);
        return 1;
    }

    start = clock();
    for (int i = 0; i < mb_to_write; i++) {
        if (read(fd, data, BUFFER_SIZE) != BUFFER_SIZE) {
            perror("\nRead failed");
            close(fd);
            free(data);
            return 1;
        }
    }
    end = clock();
    close(fd);

    double read_time = ((double)(end - start)) / CLOCKS_PER_SEC;
    double read_speed = mb_to_write / read_time;

    printf("[\033[1;32mOK\033[0m] \033[1mSequential Read:\033[0m  \033[1;32m%.2f MB/s\033[0m (%d MB in %.3fs)\n", 
           read_speed, mb_to_write, read_time);

    // Cleanup
    unlink(test_file);
    free(data);

    printf("\n\033[1;36mBenchmark Finished.\033[0m\n");
    return 0;
}
