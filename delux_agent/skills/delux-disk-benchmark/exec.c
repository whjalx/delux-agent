#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <errno.h>
#include <libgen.h>

#define BUFFER_SIZE (1024 * 1024)
#define MAX_MB      100000
#define TEMPLATE    "/tmp/delux_bench_XXXXXX"

static volatile sig_atomic_t interrupted = 0;

static void sigint_handler(int sig) { interrupted = 1; (void)sig; }

static void print_header(void) {
    printf("\033[1;36m┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\033[0m\n");
    printf("\033[1;36m┃\033[0m \033[1;35mDELUX DISK BENCHMARK (C Engine)\033[0m                  \033[1;36m┃\033[0m\n");
    printf("\033[1;36m┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\033[0m\n\n");
}

int main(int argc, char *argv[]) {
    int mb_to_write = 100;
    int json_mode = 0;

    /* --- argument parsing --- */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--json") == 0) {
            json_mode = 1;
        } else {
            char *endptr = NULL;
            long val = strtol(argv[i], &endptr, 10);
            if (*endptr != '\0' || val <= 0 || val > MAX_MB) {
                if (json_mode) {
                    printf("{\"status\":\"error\",\"error\":\"invalid size: must be 1-%d MB\"}\n", MAX_MB);
                } else {
                    fprintf(stderr, "Error: invalid size. Must be 1-%d MB.\n", MAX_MB);
                }
                return 1;
            }
            mb_to_write = (int)val;
        }
    }

    /* --- install signal handler --- */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = sigint_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    if (!json_mode) print_header();

    /* --- allocate buffer --- */
    char *data = malloc(BUFFER_SIZE);
    if (!data) {
        if (json_mode) printf("{\"status\":\"error\",\"error\":\"malloc failed\"}\n");
        else fprintf(stderr, "Error: failed to allocate buffer.\n");
        return 1;
    }
    memset(data, 'A', BUFFER_SIZE);

    /* --- create temp file --- */
    char tmpfile_path[256];
    strcpy(tmpfile_path, TEMPLATE);
    int fd = mkstemp(tmpfile_path);
    if (fd < 0) {
        if (json_mode) printf("{\"status\":\"error\",\"error\":\"cannot create temp file in /tmp: %s\"}\n", strerror(errno));
        else fprintf(stderr, "Error: cannot create temp file in /tmp: %s\n", strerror(errno));
        free(data);
        return 1;
    }

    /* ===== WRITE TEST ===== */
    if (!json_mode) {
        printf("[\033[1;33m...\033[0m] Testing \033[1mSequential Write\033[0m...\r");
        fflush(stdout);
    }

    clock_t w_start = clock();
    int w_ops = 0;
    int w_err = 0;
    int fsync_ok = 1;

    for (int i = 0; i < mb_to_write && !interrupted; i++) {
        ssize_t written = write(fd, data, BUFFER_SIZE);
        if (written != BUFFER_SIZE) {
            w_err = 1;
            break;
        }
        w_ops++;
    }

    if (!w_err && fsync(fd) != 0) {
        fsync_ok = 0;
    }
    clock_t w_end = clock();

    double w_time = ((double)(w_end - w_start)) / CLOCKS_PER_SEC;
    double w_speed = (w_time > 0 && !w_err) ? (w_ops / w_time) : 0.0;
    double w_iops = (w_time > 0 && !w_err) ? (w_ops / w_time) : 0.0;

    /* ===== READ TEST ===== */
    if (!json_mode) {
        printf("[\033[1;33m...\033[0m] Testing \033[1mSequential Read\033[0m... \r");
        fflush(stdout);
    }

    close(fd);
    fd = open(tmpfile_path, O_RDONLY);
    if (fd < 0) {
        if (json_mode) printf("{\"status\":\"error\",\"error\":\"cannot reopen temp file for reading: %s\"}\n", strerror(errno));
        else fprintf(stderr, "\nError: cannot reopen temp file for reading: %s\n", strerror(errno));
        unlink(tmpfile_path);
        free(data);
        return 1;
    }

    clock_t r_start = clock();
    int r_ops = 0;
    int r_err = 0;

    for (int i = 0; i < mb_to_write && !interrupted; i++) {
        ssize_t bytes = read(fd, data, BUFFER_SIZE);
        if (bytes != BUFFER_SIZE) {
            r_err = 1;
            break;
        }
        r_ops++;
    }
    clock_t r_end = clock();
    close(fd);

    double r_time = ((double)(r_end - r_start)) / CLOCKS_PER_SEC;
    double r_speed = (r_time > 0 && !r_err) ? (r_ops / r_time) : 0.0;
    double r_iops = (r_time > 0 && !r_err) ? (r_ops / r_time) : 0.0;

    /* --- cleanup --- */
    unlink(tmpfile_path);
    free(data);

    /* --- output --- */
    if (json_mode) {
        printf("{"
               "\"status\":\"%s\","
               "\"data\":{"
               "\"size_mb\":%d,"
               "\"buffer_bytes\":%d,"
               "\"interrupted\":%s,"
               "\"write\":{"
                   "\"time_sec\":%.6f,"
                   "\"speed_mbps\":%.2f,"
                   "\"iops\":%.2f,"
                   "\"fsync_ok\":%s,"
                   "\"error\":%s"
               "},"
               "\"read\":{"
                   "\"time_sec\":%.6f,"
                   "\"speed_mbps\":%.2f,"
                   "\"iops\":%.2f,"
                   "\"error\":%s"
               "}"
               "}}\n",
               interrupted ? "error" : "ok",
               mb_to_write,
               BUFFER_SIZE,
               interrupted ? "true" : "false",
               w_time, w_speed, w_iops,
               fsync_ok ? "true" : "false",
               w_err ? "\"write failed\"" : "null",
               r_time, r_speed, r_iops,
               r_err ? "\"read failed\"" : "null");
    } else {
        if (interrupted) {
            printf("\n\033[1;33mInterrupted.\033[0m\n");
        }
        if (w_err) {
            printf("[\033[1;31mFAIL\033[0m] Write test failed.\n");
        } else {
            printf("[\033[1;32mOK\033[0m] \033[1mSequential Write:\033[0m \033[1;32m%.2f MB/s\033[0m  "
                   "\033[2m(%d MB in %.3fs, %.0f IOPS)\033[0m%s\n",
                   w_speed, w_ops, w_time, w_iops,
                   fsync_ok ? "" : "  \033[1;33m(fsync failed)\033[0m");
        }
        if (r_err) {
            printf("[\033[1;31mFAIL\033[0m] Read test failed.\n");
        } else {
            printf("[\033[1;32mOK\033[0m] \033[1mSequential Read:\033[0m  \033[1;32m%.2f MB/s\033[0m  "
                   "\033[2m(%d MB in %.3fs, %.0f IOPS)\033[0m\n",
                   r_speed, r_ops, r_time, r_iops);
        }
        if (!w_err && !r_err) {
            printf("\n\033[1;36mBenchmark Finished.\033[0m\n");
        }
    }

    return (json_mode || (!w_err && !r_err && !interrupted)) ? 0 : 1;
}
