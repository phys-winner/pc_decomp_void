#include <stdio.h>
#include <stddef.h>
int void_probe(char *message, size_t capacity);
int main(void)
{
    char message[256] = "FAIL: probe initialization";
    int result = void_probe(message, sizeof(message));
    puts(message);
    return result;
}
